#!/usr/bin/awk
# SPDX-License-Identifier: GPL-2.0
# Copyright (C) 2019-2026 Oracle.
# awk script to extract just the failing tests

{
	if ($1 ~ /<testcase/) {
		startline = $0;
	} else if ($1 ~ /<fail/) {
		printf("%s%s</testcase>\n", startline, $0);
	} else {
		;
	}
}
