// SPDX-License-Identifier: GPL-2.0
/*
 * Copyright (C) 2018-2026 Oracle
 * Author: Darrick J. Wong <djwong@kernel.org>
 */
/* Receive fstests results tarball, stash it somewhere. */
#define _GNU_SOURCE
#include <sys/types.h>
#include <sys/stat.h>
#include <fcntl.h>
#include <stdio.h>
#include <unistd.h>
#include <stdlib.h>
#include <string.h>
#include <dirent.h>
#include <errno.h>
#include <stdarg.h>

#define BUFLEN	65536

static void
logerr(
	char *format, ...)
{
	va_list	ap;

	va_start(ap, format);
	vprintf(format, ap);
	va_end(ap);

	va_start(ap, format);
	vfprintf(stderr, format, ap);
	va_end(ap);
}

enum cformat {
	CFMT_INVALID,
	CFMT_XZ,
	CFMT_ZSTD,
	CFMT_GZIP,
};

static enum cformat compression_format(const char *buf, size_t fname_len)
{
	static char xz_suffix[] = ".tar.xz";
	static char zst_suffix[] = ".tar.zst";
	static char gzip_suffix[] = ".tar.gz";
	const char *suffix;

	if (fname_len > sizeof(xz_suffix)) {
		suffix = buf + fname_len - sizeof(xz_suffix) + 1;
		if (!memcmp(suffix, xz_suffix, sizeof(xz_suffix)))
			return CFMT_XZ;
	}

	if (fname_len > sizeof(zst_suffix)) {
		suffix = buf + fname_len - sizeof(zst_suffix) + 1;
		if (!memcmp(suffix, zst_suffix, sizeof(zst_suffix)))
			return CFMT_ZSTD;
	}

	if (fname_len > sizeof(gzip_suffix)) {
		suffix = buf + fname_len - sizeof(gzip_suffix) + 1;
		if (!memcmp(suffix, gzip_suffix, sizeof(gzip_suffix)))
			return CFMT_GZIP;
	}

	return CFMT_INVALID;
}

static int is_xz(const char *buf, size_t bufsz)
{
	static char xz_header[] = { 0xFD, '7', 'z', 'X', 'Z', 0 };

	return bufsz >= sizeof(xz_header) &&
		memcmp(buf, xz_header, sizeof(xz_header)) == 0;
}

static int is_zst(const char *buf, size_t bufsz)
{
	static char zst_header[] = { 0x28, 0xb5, 0x2f, 0xfd };

	return bufsz >= sizeof(zst_header) &&
		memcmp(buf, zst_header, sizeof(zst_header)) == 0;
}

static int is_gzip(const char *buf, size_t bufsz)
{
	static char gzip_header[] = { 0x1f, 0x8b };

	return bufsz >= sizeof(gzip_header) &&
		memcmp(buf, gzip_header, sizeof(gzip_header)) == 0;
}

int
main(
	int		argc,
	char		*argv[])
{
	char		tmpfile[MAXNAMLEN];
	char		*buf, *buf2;
	char		*fname;
	ssize_t		sz, sz2;
	ssize_t		fname_len;
	enum cformat	cfmt;
	int		tmpfile_fd;
	int		ret;

	/* Allocate buffer. */
	buf = malloc(BUFLEN);
	if (!buf) {
		logerr("malloc: %s\n", strerror(errno));
		return 1;
	}

	/* Read buffer.  Filename should be the first null-terminated string. */
	sz = read(STDIN_FILENO, buf, BUFLEN);
	if (sz < 0) {
		logerr("read input: %s\n", strerror(errno));
		return 1;
	}
	if (sz == 0) {
		logerr("short read\n");
		return 1;
	}

	/*
	 * Make sure the filename isn't too long and does not contain path
	 * separators.
	 */
	fname_len = strnlen(buf, BUFLEN);
	if (fname_len >= MAXNAMLEN) {
		logerr("file name too long\n");
		return 1;
	}

	if (strchr(buf, '/')) {
		logerr("file name contains path components\n");
		return 1;
	}

	cfmt = compression_format(buf, fname_len);
	if (cfmt == CFMT_INVALID) {
		logerr("cannot determine file type from: %s\n", buf);
		return 1;
	}

	fname = strdup(buf);
	if (!fname) {
		logerr("saving file name: %s\n", strerror(errno));
		return 1;
	}

	/* Advance our buffer pointer, and make sure this is an .xz file. */
	buf2 = buf + fname_len + 1;
	sz -= fname_len + 1;

	switch (cfmt) {
	case CFMT_XZ:
		if (!is_xz(buf2, sz)) {
			logerr("not a xz compressed file?\n");
			return 1;
		}
		break;
	case CFMT_ZSTD:
		if (!is_zst(buf2, sz)) {
			logerr("not a zstd compressed file?\n");
			return 1;
		}
		break;
	case CFMT_GZIP:
		if (!is_gzip(buf2, sz)) {
			logerr("not a gzip compressed file?\n");
			return 1;
		}
		break;
	case CFMT_INVALID:
		logerr("invalid format?\n");
		return 1;
		break;
	}

	/* Open temporary file and store incoming contents. */
	snprintf(tmpfile, sizeof(tmpfile), ".fstmatrix-%d-XXXXXX", getpid());
	tmpfile_fd = mkstemp(tmpfile);
	if (tmpfile_fd < 0) {
		logerr("tempfile: %s\n", strerror(errno));
		return 1;
	}

	while (sz > 0) {
		sz2 = write(tmpfile_fd, buf2, sz);
		if (sz2 < 0) {
			perror("buffer write");
			goto unlink;
		}
		if (sz2 != sz) {
			logerr("short write %zd, have %zd\n", sz2, sz);
			goto unlink;
		}

		buf2 = buf;
		sz = read(STDIN_FILENO, buf, BUFLEN);
	}
	if (sz < 0) {
		perror("short buffer read");
		goto unlink;
	}

	ret = fchmod(tmpfile_fd, 0666);
	if (ret) {
		perror("fchmod");
		goto unlink;
	}

	/* Flush contents to disk. */
	ret = fsync(tmpfile_fd);
	if (ret) {
		perror("flushing buffer to disk");
		goto unlink;
	}
	ret = close(tmpfile_fd);
	if (ret) {
		perror("closing tempfile");
		goto unlink;
	}

	/* Rename the temporary file to the one we were given. */
	ret = renameat(AT_FDCWD, tmpfile, AT_FDCWD, fname);
	if (ret) {
		perror("renaming file");
		goto unlink;
	}

	return 0;
unlink:
	ret = unlink(tmpfile);
	if (ret)
		logerr("removing tempfile: %s\n", strerror(errno));
	return 1;
}
