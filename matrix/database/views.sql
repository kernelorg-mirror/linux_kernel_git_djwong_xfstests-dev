/*
 * SPDX-License-Identifier: GPL-2.0
 * Copyright (C) 2019-2026 Oracle.
 *
 * Main database schema for fstests results.
 */
DROP VIEW IF EXISTS avg_test_runtime;
DROP VIEW IF EXISTS avg_test_machine_runtime;
DROP VIEW IF EXISTS avg_test_kernel_runtime;
DROP VIEW IF EXISTS check_time;
DROP VIEW IF EXISTS machine_with_name;

CREATE VIEW avg_test_runtime AS
	SELECT
		test_name.name AS test_name,
		ROUND(AVG(result.runtime)) AS avg_runtime,
		ROUND(STDEV(result.runtime)) AS stddev_runtime
	FROM
		test_name, result
	WHERE
		test_name.id = result.test_id
	GROUP BY
		test_name.name;

CREATE VIEW check_time AS
	SELECT
		test_name.name AS test_name,
		hash.value AS machine_hash,
		CAST(AVG(result.runtime) AS INT) AS avg_runtime
	FROM
		test_name, result, machine, test_run, hash
	WHERE
		test_name.id = result.test_id AND
		test_run.id = result.test_run_id AND
		machine.id = test_run.machine_id AND
		machine.hash_id = hash.id
	GROUP BY
		test_name.name, hash.id;

CREATE VIEW avg_test_machine_runtime AS
	SELECT
		test_name.name AS test_name,
		machine_name.name AS machine_name,
		CAST(AVG(result.runtime) AS INT) AS avg_runtime,
		CAST(STDEV(result.runtime) AS INT) AS stddev_runtime
	FROM
		test_name, result, machine, test_run, machine_name, hash
	WHERE
		test_name.id = result.test_id AND
		test_run.id = result.test_run_id AND
		machine.id = test_run.machine_id AND
		machine_name.machine_id = machine.id AND
		machine.hash_id = hash.id
	GROUP BY
		test_name.name, hash.id;

CREATE VIEW avg_test_kernel_runtime AS
	SELECT
		test_name.name AS test_name,
		test_run.kernel AS kernel,
		CAST(AVG(result.runtime) AS INT) AS avg_runtime,
		CAST(STDEV(result.runtime) AS INT) AS stddev_runtime
	FROM
		test_name, result, test_run
	WHERE
		test_name.id = result.test_id AND
		test_run.id = result.test_run_id
	GROUP BY
		test_name.name, test_run.kernel;

CREATE VIEW machine_with_name AS
	SELECT
		hash.value as hash,
		machine.arch,
		machine.ram_mb,
		machine.cpus,
		machine.nodes,
		machine.nr_disk,
		machine.disk_mb,
		machine.nr_pmem,
		machine.pmem_mb,
		machine.mtime,
		machine_name.name AS name,
		machine_name.mtime AS name_mtime
	FROM
		machine, machine_name, hash
	WHERE
		machine.id = machine_name.machine_id AND
		machine.hash_id = hash.id;
