/*
 * SPDX-License-Identifier: GPL-2.0
 * Copyright (C) 2019-2026 Oracle.
 *
 * Main database schema for fstests results.
 */
DROP TABLE IF EXISTS hash;
DROP TABLE IF EXISTS machine;
DROP TABLE IF EXISTS machine_name;
DROP TABLE IF EXISTS test;
DROP TABLE IF EXISTS test_name;
DROP TABLE IF EXISTS test_run;
DROP TABLE IF EXISTS result_type;
DROP TABLE IF EXISTS result;

PRAGMA foreign_keys = ON;

CREATE TABLE hash(
	id		INTEGER PRIMARY KEY NOT NULL,
	value		TEXT UNIQUE NOT NULL,
	mtime		DATE NOT NULL
);
CREATE TABLE machine(
	id		INTEGER PRIMARY KEY NOT NULL,
	hash_id		INTEGER NOT NULL,
	arch		TEXT NOT NULL,
	ram_mb		INTEGER NOT NULL,
	cpus		INTEGER NOT NULL,
	nodes		INTEGER NOT NULL,
	nr_disk		INTEGER NOT NULL,
	disk_mb		INTEGER NOT NULL,
	nr_pmem		INTEGER NOT NULL,
	pmem_mb		INTEGER NOT NULL,
	mtime		DATE NOT NULL,

	FOREIGN KEY(hash_id)		REFERENCES hash(id)
);
CREATE TABLE machine_name(
	id		INTEGER PRIMARY KEY NOT NULL,
	name		TEXT UNIQUE NOT NULL,
	machine_id	INTEGER NOT NULL,
	mtime		DATE NOT NULL,

	FOREIGN KEY(machine_id)		REFERENCES machine(id)
);
CREATE TABLE test_run(
	id		INTEGER PRIMARY KEY NOT NULL,
	hash_id		INTEGER NOT NULL,
	machine_id	INTEGER NOT NULL,
	machine_name_id	INTEGER NOT NULL,
	start_time	DATE NOT NULL,
	mtime		DATE NOT NULL,
	fstyp		TEXT NOT NULL,
	kernel		TEXT,
	mount_opts	TEXT,
	mkfs_opts	TEXT,
	check_opts	TEXT,
	time_factor	INTEGER,
	load_factor	INTEGER,
	test_dir	TEXT,
	test_dev	TEXT,
	scratch_mnt	TEXT,
	scratch_dev	TEXT,
	section		TEXT,
	run_time	INTEGER,
	failed		INTEGER NOT NULL,
	skipped		INTEGER NOT NULL,
	tried		INTEGER NOT NULL,
	counted		INTEGER NOT NULL,

	FOREIGN KEY(hash_id)		REFERENCES hash(id)
	FOREIGN KEY(machine_id)		REFERENCES machine(id)
	FOREIGN KEY(machine_name_id)	REFERENCES machine_name(id)
);
CREATE TABLE test(
	id		INTEGER PRIMARY KEY NOT NULL,
	hash_id		INTEGER NOT NULL,
	mtime		DATE NOT NULL,

	FOREIGN KEY(hash_id)		REFERENCES hash(id)
);
CREATE TABLE test_name(
	id		INTEGER PRIMARY KEY NOT NULL,
	name		TEXT UNIQUE NOT NULL,
	test_id		INTEGER NOT NULL,
	mtime		DATE NOT NULL,

	FOREIGN KEY(test_id)		REFERENCES test(id)
);
CREATE TABLE groups(
	id		INTEGER PRIMARY KEY NOT NULL,
	name		TEXT UNIQUE NOT NULL,
	mtime		DATE NOT NULL
);
CREATE TABLE test_group(
	id		INTEGER PRIMARY KEY NOT NULL,
	test_id		INTEGER NOT NULL,
	group_id	INTEGER NOT NULL,
	mtime		DATE NOT NULL,

	FOREIGN KEY(test_id)		REFERENCES test(id)
	FOREIGN KEY(group_id)		REFERENCES groups(id)
);
CREATE TABLE result_type(
	id		INTEGER PRIMARY KEY NOT NULL,
	name		TEXT UNIQUE NOT NULL,
	mtime		DATE NOT NULL
);
CREATE TABLE result(
	id		INTEGER PRIMARY KEY NOT NULL,
	test_run_id	INTEGER NOT NULL,
	test_id		INTEGER NOT NULL,
	result_type_id	INTEGER NOT NULL,
	runtime		INTEGER NOT NULL,
	has_diff	BOOLEAN NOT NULL,
	has_full	BOOLEAN NOT NULL,
	has_dmesg	BOOLEAN NOT NULL,
	mtime		DATE NOT NULL,

	FOREIGN KEY(test_run_id)	REFERENCES test_run(id),
	FOREIGN KEY(test_id)		REFERENCES test(id),
	FOREIGN KEY(result_type_id)	REFERENCES result_type(id)
);
