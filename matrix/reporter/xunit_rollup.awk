#!/usr/bin/awk
# SPDX-License-Identifier: GPL-2.0
# Copyright (C) 2019-2026 Oracle.
# awk script to filter the golden output and error messages out of an xunit
# xml file.

BEGIN {
	ignore = 0;
}
{
	if ($1 ~ /<system-(out|err)>/) {
		ignore = 1;
	} else if ($1 ~ /<\/system-(out|err)>/) {
		ignore = 0;
	} else if (ignore) {
		;
	} else if ($1 ~ /<properties/) {
		printf("%s\n\t\t<property name=\"KERNEL\" value=\"%s\"/>\n", $0, kernel);
	} else {
		print $0;
	}
}
