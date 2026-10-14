/*
 * SPDX-License-Identifier: GPL-2.0
 * Copyright (C) 2019-2026 Oracle.
 *
 * Main index schema for fstests results.
 */
DROP INDEX IF EXISTS m_hash;
DROP INDEX IF EXISTS mn_name;
DROP INDEX IF EXISTS tr_hash;
DROP INDEX IF EXISTS t_hash;
DROP INDEX IF EXISTS tn_name;
DROP INDEX IF EXISTS g_name;
DROP INDEX IF EXISTS rt_name;
DROP INDEX IF EXISTS r_testrunid;
DROP INDEX IF EXISTS r_testid;
DROP INDEX IF EXISTS h_hash;

CREATE INDEX h_value ON hash(value);
CREATE INDEX m_hash ON machine(hash_id);
CREATE INDEX mn_name ON machine_name(name);
CREATE INDEX tr_hash ON test_run(hash_id);
CREATE INDEX t_hash ON test(hash_id);
CREATE INDEX tn_name ON test_name(name);
CREATE INDEX g_name ON groups(name);
CREATE INDEX rt_name ON result_type(name);
CREATE INDEX r_testrunid ON result(test_run_id);
CREATE INDEX r_testid ON result(test_id);
