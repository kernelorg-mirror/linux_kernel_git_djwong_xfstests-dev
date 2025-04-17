// SPDX-License-Identifier: GPL-2.0+
/*
 * Copyright (C) 2025 Oracle. All Rights Reserved.
 * Author: Darrick J. Wong <djwong@kernel.org>
 *
 * Open a block device with O_EXCL to ensure it's not in use by anyone.
 */
#include <string.h>
#include <stdio.h>
#include <stdlib.h>
#include <fcntl.h>

int main(int argc, char *argv[])
{
	int fd;

	if (argc == 1 || !strcmp(argv[1], "--help")) {
		printf("Usage: %s bdev\n", argv[0]);
		exit(1);
	}

	fd = open(argv[1], O_RDONLY | O_EXCL);
	if (fd < 1) {
		perror(argv[1]);
		exit(1);
	}

	exit(0);
}
