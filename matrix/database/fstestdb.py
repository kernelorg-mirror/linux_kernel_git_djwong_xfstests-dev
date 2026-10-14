#! /usr/bin/python3
# SPDX-License-Identifier: GPL-2.0
# Copyright (C) 2019-2026 Oracle.

# Object library for fstests test result objects

import os
import sqlite3
import sys
import tokenize
import io
import fcntl
import copy
import time

# Set debugging info
if 'DBG' in os.environ:
	try:
		DEBUG = int(os.environ['DBG'])
	except:
		DEBUG = 1
else:
	DEBUG = 0

UPD_UPDATE = 1
UPD_INSERT = 2

def sqlite_dict_factory(cursor, row):
	d = {}
	for idx, col in enumerate(cursor.description):
		d[col[0]] = row[idx]
	return d

class Database(object):
	'''Wrapper for database objects.'''
	def __init__(self, fsmatrix_dir, readonly = True):
		dbfile = f'{fsmatrix_dir}/fstests.db'
		self.fd = open(dbfile)

		# sqlite sucks at concurrency, so we use flock locks to ensure
		# that only one program accesses the db at a time
		if readonly:
			fcntl.flock(self.fd, fcntl.LOCK_SH)
			db = f'file:{dbfile}?mode=ro'
		else:
			fcntl.flock(self.fd, fcntl.LOCK_EX)
			db = f'file:{dbfile}?mode=rwc'

		self.conn = sqlite3.connect(db, uri = True)
		self.conn.row_factory = sqlite_dict_factory

		# Use the write ahead log, which also sets synchronous = NORMAL
		if not readonly:
			self.conn.execute('PRAGMA journal_mode = WAL')

		# 2GB of mmap memory or cache
		self.conn.execute('PRAGMA mmap_size = 2147483648')
		self.conn.execute('PRAGMA cache_size = -2097152')
		self.in_update = False

	def __del__(self):
		self.conn.close()
		fcntl.flock(self.fd, fcntl.LOCK_UN)
		self.fd.close()

	def dirty(self):
		return self.in_update

	def try_begin_update(self):
		if not self.in_update:
			self.begin_update()

	def begin_update(self):
		assert not self.in_update

		self.conn.execute('BEGIN TRANSACTION')
		self.in_update = True

	def cancel_update(self):
		assert self.in_update

		self.conn.execute('ROLLBACK TRANSACTION')
		self.in_update = False

	def commit_update(self):
		assert self.in_update

		self.conn.execute('COMMIT TRANSACTION')
		self.conn.commit()
		self.in_update = False

	def __execute(self, sql, values = ()):
		if DEBUG:
			print(sql, values)
		return self.conn.execute(sql, values)

	def __needs_update(self, sql, values):
		'''Does this object need to be inserted, updated, or nothing?'''
		cur = self.__execute(sql, values)
		if cur.fetchone() == None:
			return UPD_INSERT
		return UPD_UPDATE

	def fetch(self, table, attrs, object_keys):
		'''Return a dictionary for this object's database attrs.'''
		#assert len(attrs & set(object_keys)) == len(object_keys)

		where_criteria = []
		where_values = []

		#SELECT attr1, attr2 FROM table
		# WHERE
		#	(key1 = ?)

		for k in object_keys:
			where_criteria.append('(%s = ?)' % k)
			where_values.append(object_keys[k])
		
		if DEBUG > 1:
			print('table', table)
			print('wc', where_criteria)
			print('wv', where_values)

		# Create the SELECT statement for fetch
		sql = 'SELECT %s FROM %s WHERE %s' % \
				(', '.join(attrs), table, ' AND '.join(where_criteria))
		cur = self.__execute(sql, where_values)

		# Return the (unique?) result
		ret = cur.fetchone()
		assert cur.fetchone() == None
		return ret

	def upsert(self, table, dictionary, object_keys, mtime_key, db_key):
		'''Make sure the db @table contains a row for @dictionary '''
		'''with the given @object_keys and a modification time kept '''
		'''in @mtime_key.'''
		assert len(set(dictionary) & object_keys) == len(object_keys)
		assert mtime_key not in object_keys
		assert self.in_update

		if DEBUG > 1:
			print(('starting an upsert', table, dictionary,
				object_keys, mtime_key, db_key))

		mtime = dictionary[mtime_key]
		attrs = list(set(dictionary) - object_keys)

		insert_attrs = ', '.join(attrs + list(object_keys))
		insert_values = []
		update_setters = []
		where_criteria = []
		set_values = []
		where_values = []

		def obj_key(o):
			for field in o.fields:
				if o.fields[field].object_key:
					return field
			assert False

		# These are the SQL statements we're trying to construct:

		# Fast update if we already have a key
		#UPDATE table SET
		#	(attr1 = ?,
		#	attr2 = (SELECT id FROM table3 WHERE hash = ?))
		# WHERE
		#	(id = ?)
		for db_attr in db_key:
			for k in attrs:
				obj = dictionary[k]
				if not isinstance(obj, DatabaseObject):
					update_setters.append('%s = ?' % k)
					set_values.append(obj)
					continue
				ok = obj_key(obj)
				vstr = '(SELECT %s FROM %s WHERE %s = ?)' % \
						(obj.db_key, obj.table_name, ok)
				update_setters.append('%s = %s' % (k, vstr))

				key = getattr(obj, ok)
				if not isinstance(key, DatabaseObject):
					set_values.append(key)
					continue

				value = getattr(key, key.db_key)
				set_values.append(value)

			# Create the UPDATE statement for objects that do exist
			sql = 'UPDATE %s SET %s WHERE %s = ?' % \
					(table, ', '.join(update_setters), db_attr)
			set_values.append(db_key[db_attr])
			values = tuple(set_values)
			self.__execute(sql, values)
			return

		# Figure out if there's already an object in the table
		#SELECT mtime FROM table
		# WHERE
		#	(key1 = ?) AND
		#	(key2 = (SELECT id FROM table2 WHERE hash = ?))

		# Insert new object into table
		#INSERT INTO table
		#	(attr1, attr2, key1, key2)
		# VALUES
		#	(?,
		#	(SELECT id FROM table3 WHERE hash = ?),
		#	?,
		#	?)

		# Update object if we don't have a key
		#UPDATE table SET
		#	(attr1 = ?,
		#	attr2 = (SELECT id FROM table3 WHERE hash = ?))
		# WHERE
		#	(key1 = ?) AND
		#	(key2 = (SELECT id FROM table2 WHERE hash = ?))

		# Non-keys go first because they can be changed at any time
		for k in attrs:
			obj = dictionary[k]
			if not isinstance(obj, DatabaseObject):
				insert_values.append('?')
				update_setters.append('%s = ?' % k)
				set_values.append(obj)
				continue
			ok = obj_key(obj)
			vstr = '(SELECT %s FROM %s WHERE %s = ?)' % \
					(obj.db_key, obj.table_name, ok)
			insert_values.append(vstr)
			update_setters.append('%s = %s' % (k, vstr))

			key = getattr(obj, ok)
			if not isinstance(key, DatabaseObject):
				set_values.append(key)
				continue

			value = getattr(key, key.db_key)
			set_values.append(value)

		# Record keys go last so that we can put the WHERE clause at
		# the end.
		for k in object_keys:
			obj = dictionary[k]
			if not isinstance(obj, DatabaseObject):
				insert_values.append('?')
				where_criteria.append('(%s = ?)' % k)
				where_values.append(obj)
				continue
			ok = obj_key(obj)
			vstr = '(SELECT %s FROM %s WHERE %s = ?)' % \
					(obj.db_key, obj.table_name, ok)
			insert_values.append(vstr)
			where_criteria.append('(%s = %s)' % (k, vstr))

			key = getattr(obj, ok)
			if not isinstance(key, DatabaseObject):
				where_values.append(key)
				continue

			value = getattr(key, key.db_key)
			where_values.append(value)

		if DEBUG > 1:
			print('mtime_key', mtime_key)
			print('table', table)
			print('ia', insert_attrs)
			print('iv', insert_values)
			print('us', update_setters)
			print('wc', where_criteria)
			print('sv', set_values)
			print('wv', where_values)

		# Create the SELECT statement for if-modified-since
		status_sql = 'SELECT %s FROM %s WHERE %s' % \
				(mtime_key, table, ' AND '.join(where_criteria))

		# Create the INSERT statment for objects that don't exist
		insert_sql = 'INSERT INTO %s (%s) VALUES (%s)' % \
				(table, insert_attrs, ', '.join(insert_values))

		# Create the UPDATE statement for objects that do exist
		update_sql = 'UPDATE %s SET %s WHERE %s' % \
				(table, ', '.join(update_setters), \
				 ' AND '.join(where_criteria))

		# Figure out what our action is going to be, and do it
		upd = self.__needs_update(status_sql, tuple(where_values))
		if upd == UPD_INSERT:
			sql = insert_sql
		else:
			sql = update_sql
		values = tuple(set_values + where_values)
		self.__execute(sql, values)

class DatabaseObjectField(object):
	'''Attribute of an object.'''
	def __init__(self, type, default = None, object_key = False, optional = False):
		assert default is None or isinstance(default, type)

		self.type = type
		self.default = default
		self.object_key = object_key
		self.optional = optional and not object_key

	def sql(self, value):
		'''Return the value ready for sql upload.'''
		return None if value is None else self.type(value)

fld = DatabaseObjectField

class DatabaseObjectRelation(DatabaseObjectField):
	'''Relation between objects.'''
	def __init__(self, type, object_key = False):
		super().__init__(type, None, object_key)

	def sql(self, value):
		'''Return the value ready for sql upload.'''
		assert value is not None
		assert isinstance(value, self.type)
		assert isinstance(value, DatabaseObject)

		return value

rel = DatabaseObjectRelation

class DatabaseObject(object):
	'''Base class of database objects.'''
	db_key = 'id'
	obj_mtime = 'mtime'
	def __init__(self, **kwargs):
		'''Initialize an object with given attributes.'''
		assert hasattr(self, 'fields')
		assert hasattr(self, 'table_name')
		assert len([x for x in self.fields if self.fields[x].object_key]) > 0

		setattr(self, type(self).db_key, None)
		self.dirty = False
		relations = set([x for x in self.fields if isinstance(x, DatabaseObjectRelation)])

		# Complain about unrecognized attributes
		leftovers = set(kwargs) - set(self.fields)
		if len(leftovers) != 0:
			print(kwargs)
			print(self.fields)
			print(relations)
			print(leftovers)
			assert len(leftovers) == 0

		# Internal db primary key shouldn't be an attr
		assert self.db_key not in self.fields

		# mtime must be a non-relation attribute
		assert self.obj_mtime in self.fields

		for a in self.fields:
			v = kwargs[a] if a in kwargs else self.fields[a].default
			setattr(self, a, v)

		for a in relations:
			# Relations must be set at construction time
			assert hasattr(self, a)

	def needs_update(self, timestamp):
		'''Return true if the timestamp is newer than the object mtime.'''
		obj_mtime = getattr(self, self.obj_mtime, None)
		if obj_mtime is None:
			return True
		return obj_mtime < timestamp

	def obj_key(self):
		'''Return a tuple that can be used to identify this object.'''

		obj_key = []
		for field in self.fields:
			if self.fields[field].object_key:
				obj = getattr(self, field)
				if isinstance(obj, DatabaseObject):
					value = getattr(obj, obj.db_key)
					obj_key.append(value)
				else:
					obj_key.append(obj)
		return tuple(obj_key)

	def assert_formed(self):
		'''Is this object fully specified?'''
		for name in self.fields:
			field = self.fields[name]

			obj = getattr(self, name, None)
			if isinstance(field, DatabaseObjectRelation):
				# relations are always required
				if obj is None:
					raise Exception(f'{self}.{name} relation is None')
				obj.assert_formed()
			elif not field.optional and obj is None:
				raise Exception(f'{self}.{name} is None')
		return True

	def reconnect(self, db):
		'''Connect an object with related objects.'''

		for name in self.fields:
			field = self.fields[name]

			if not isinstance(field, DatabaseObjectRelation):
				continue

			obj = getattr(self, name)
			if obj is None:
				continue
			try:
				obj.assert_formed()
				continue
			except:
				pass

			# Substitute this object for one in the object manager
			# if such a thing exists.
			ret = ObjectManager.find_object(obj)
			if ret is None:
				ObjectManager.store_object(obj)
			elif ret != obj:
				obj = ret
				# connect to existing object
				setattr(self, name, ret)
			obj.reconnect(db)

	def persist(self, db):
		'''Persist this object and its children to the database.'''
		self.reconnect(db)

		for name in self.fields:
			field = self.fields[name]

			if not isinstance(field, DatabaseObjectRelation):
				continue

			obj = getattr(self, name)
			assert obj is not None
			obj.persist(db)

		self.upsert(db)

	def db_keys(self):
		'''Return a dictionary of this object's database keys.'''
		obj_keys = {}
		for x in self.fields:
			if self.fields[x].object_key:
				obj = getattr(self, x)
				if isinstance(obj, DatabaseObject):
					obj_keys[x] = getattr(obj, obj.db_key)
				else:
					obj_keys[x] = obj
		return obj_keys

	def get_db_id(self, db):
		'''Fetch this object's db table id.'''
		assert getattr(self, self.db_key, None) == None

		obj_keys = self.db_keys()
		attrs = db.fetch(self.table_name, [self.db_key], obj_keys)
		if attrs is None:
			return
		setattr(self, self.db_key, attrs[self.db_key])
		return attrs[self.db_key]

	def fetch(self, db, raw_id = None):
		'''Fetch this object's attributes from the database.'''
		fetch_fields = copy.copy(self.fields)
		fetch_fields[self.db_key] = fld(int)

		if raw_id is not None:
			# Deserialize based on a table id
			obj_keys = {self.db_key: raw_id}
		else:
			# Create a dictionary of the primary keys & values
			obj_keys = self.db_keys()

		attrs = db.fetch(self.table_name, set(fetch_fields), obj_keys)
		if attrs is None:
			return

		setattr(self, self.db_key, attrs[self.db_key])

		# Populate the object.  We had better get all the fields...
		for name in self.fields:
			field = self.fields[name]

			if not isinstance(field, DatabaseObjectRelation):
				setattr(self, name, attrs[name])
				continue

			# Construct a template object and see if we already
			# have one registered.
			template = field.type()
			template.fetch(db, attrs[name])
			obj = ObjectManager.find_object(template)
			if obj is None:
				# Nothing registered; store this unconnected
				# prototype
				ObjectManager.store_object(template)
				obj = template
			setattr(self, name, obj)

		self.dirty = False

	@classmethod
	def resurrect(cls, db, **kwargs):
		'''Resurrect a database object from key data.'''

		template = cls(**kwargs)
		ret = ObjectManager.find_object(template)
		if ret is not None:
			ret.reconnect(db)
			return ret
		else:
			ret = template
			ret.fetch(db)
			ObjectManager.store_object(ret)
		ret.reconnect(db)
		return ret

	@classmethod
	def predicate(cls, field, op, value):
		'''Convenience method to construct field predicates.'''
		return FieldPredicate(cls, field, op, value)

class MutableDatabaseObject(DatabaseObject):
	'''Mutable database object.'''

	def map_vars(self):
		'''Default function to map SQL attributes to object fields, '''
		'''assuming attributes and fields have the same name.'''
		r = {}
		for d in self.fields:
			o = getattr(self, d)
			r[d] = self.fields[d].sql(o)
		return r

	def upsert(self, db):
		'''Make sure this object exists in the database.'''
		self.assert_formed()

		if not self.dirty:
			return

		db_val = getattr(self, self.db_key)
		if db_val is not None:
			db_key = {self.db_key: db_val}
		else:
			db_key = {}

		obj_keys = set([x for x in self.fields if self.fields[x].object_key])
		db.upsert(self.table_name, self.map_vars(), obj_keys, \
				self.obj_mtime, db_key)
		self.dirty = False
		if db_val is None:
			self.get_db_id(db)

	def set_attr(self, name, value):
		'''Set a value.'''
		assert name in self.fields
		assert not isinstance(self.fields[name], DatabaseObjectRelation)

		if not hasattr(self, name):
			print('%s: attr not found in %s.' % (name, self),
					file = sys.stderr)
			assert hasattr(self, name)

		if getattr(self, name, None) != value:
			self.dirty = True
		setattr(self, name, value)

	def set_relation(self, name, rel):
		'''Set a relationship.'''
		assert name in self.fields
		assert isinstance(self.fields[name], DatabaseObjectRelation)
		assert isinstance(rel, self.fields[name].type)

		if getattr(self, name, None) != rel:
			self.dirty = True
		setattr(self, name, rel)

	def touch(self, lastmod):
		'''Set the last modification time.'''
		self.set_attr(self.obj_mtime, int(lastmod))

class Hash(MutableDatabaseObject):
	'''Hash string table object.'''
	table_name = 'hash'
	fields = {
		'value':	fld(str, object_key = True),
		'mtime':	fld(int),
	}
	def __init__(self, **kwargs):
		super().__init__(**kwargs)

class Machine(MutableDatabaseObject):
	'''Profile of a testing machine configuration.'''
	table_name = 'machine'
	fields = {
		'hash_id':	rel(Hash, object_key = True),
		'arch':		fld(str),
		'cpus':		fld(int),
		'nodes':	fld(int, default = 0),
		'ram_mb':	fld(int),
		'nr_pmem':	fld(int, default = 0),
		'pmem_mb':	fld(int, default = 0),
		'nr_disk':	fld(int, default = 0),
		'disk_mb':	fld(int, default = 0),
		'mtime':	fld(int),
	}
	def __init__(self, **kwargs):
		super().__init__(**kwargs)

	def reset_storage(self):
		'''Reset the storage counters.'''
		self.nr_pmem = 0
		self.pmem_mb = 0
		self.nr_disk = 0
		self.disk_mb = 0

	def add_pmem(self, size_mb):
		'''Add a persistent memory device.'''
		self.nr_pmem += 1
		self.pmem_mb += size_mb

	def add_disk(self, size_mb):
		'''Add a disk device.'''
		self.nr_disk += 1
		self.disk_mb += size_mb

	def summarize_storage(self):
		'''Average the storage amount.'''
		if self.nr_pmem > 0:
			self.pmem_mb = int(self.pmem_mb / self.nr_pmem)
		if self.nr_disk > 0:
			self.disk_mb = int(self.disk_mb / self.nr_disk)

class MachineName(MutableDatabaseObject):
	'''Mapping of machine name to machine configuration.'''
	table_name = 'machine_name'
	fields = {
		'machine_id':	rel(Machine),
		'name':		fld(str, object_key = True),
		'mtime':	fld(int),
	}
	def __init__(self, **kwargs):
		super().__init__(**kwargs)

class TestRun(MutableDatabaseObject):
	'''Summary of an invocation of the fstests.'''
	table_name = 'test_run'
	fields = {
		'hash_id':	rel(Hash, object_key = True),
		'machine_id':	rel(Machine),
		'machine_name_id': rel(MachineName),
		'start_time':	fld(int),
		'mtime':	fld(int),
		'fstyp':	fld(str),
		'kernel':	fld(str, optional = True),
		'mount_opts':	fld(str, optional = True),
		'mkfs_opts':	fld(str, optional = True),
		'check_opts':	fld(str, optional = True),
		'time_factor':	fld(int, default = 1, optional = True),
		'load_factor':	fld(int, default = 1, optional = True),
		'test_dir':	fld(str, optional = True),
		'test_dev':	fld(str, optional = True),
		'scratch_mnt':	fld(str, optional = True),
		'scratch_dev':	fld(str, optional = True),
		'section':	fld(str, optional = True),
		'run_time':	fld(int, optional = True),
		'failed':	fld(int),
		'skipped':	fld(int),
		'tried':	fld(int),
		'counted':	fld(int),
	}
	def __init__(self, **kwargs):
		super().__init__(**kwargs)

class Test(MutableDatabaseObject):
	'''Test case.  We identify a test case based on its header comment.'''
	table_name = 'test'
	fields = {
		'hash_id':	rel(Hash, object_key = True),
		'mtime':	fld(int),
	}
	def __init__(self, **kwargs):
		super().__init__(**kwargs)

class TestName(MutableDatabaseObject):
	'''Mapping of test name to test case.'''
	table_name = 'test_name'
	fields = {
		'test_id':	rel(Test),
		'name':		fld(str, object_key = True),
		'mtime':	fld(int),
	}
	def __init__(self, **kwargs):
		super().__init__(**kwargs)

class Group(MutableDatabaseObject):
	'''Group of test cases.'''
	table_name = 'groups'
	fields = {
		'name':		fld(str, object_key = True),
		'mtime':	fld(int),
	}
	def __init__(self, **kwargs):
		self.members = set()
		super().__init__(**kwargs)

	def add_member(self, member):
		'''Add a group member to this group.'''
		assert member.group == self
		self.members.add(member)

class GroupMember(MutableDatabaseObject):
	'''Mapping of group to test case.'''
	table_name = 'test_group'
	fields = {
		'group_id':	rel(Group, object_key = True),
		'test_id':	rel(Test, object_key = True),
		'mtime':	fld(int),
	}
	def __init__(self, **kwargs):
		super().__init__(**kwargs)

class ResultType(MutableDatabaseObject):
	'''Test result type.'''
	table_name = 'result_type'
	fields = {
		'name':		fld(str, object_key = True),
		'mtime':	fld(int),
	}
	def __init__(self, **kwargs):
		super().__init__(**kwargs)

class Result(MutableDatabaseObject):
	'''Mapping of test run and test to a result.'''
	table_name = 'result'
	fields = {
		'test_run_id':	rel(TestRun, object_key = True),
		'test_id':	rel(Test, object_key = True),
		'result_type_id': rel(ResultType),
		'runtime':	fld(int, 0),
		'has_diff':	fld(bool, False),
		'has_full':	fld(bool, False),
		'has_dmesg':	fld(bool, False),
		'mtime':	fld(int),
	}
	def __init__(self, **kwargs):
		super().__init__(**kwargs)

class MachineWithName(DatabaseObject):
	'''Cross product of machine and name.'''
	table_name = 'machine_with_name'
	fields = {
		'hash':		fld(str),
		'arch':		fld(str),
		'cpus':		fld(int),
		'nodes':	fld(int, 0),
		'ram_mb':	fld(int),
		'nr_pmem':	fld(int, 0),
		'pmem_mb':	fld(int, 0),
		'nr_disk':	fld(int, 0),
		'disk_mb':	fld(int, 0),
		'mtime':	fld(int),
		'name':		fld(str, object_key = True),
		'name_mtime':	fld(int),
	}
	def __init__(self, **kwargs):
		super().__init__(**kwargs)

# Object Manager...
class ObjectManager(object):
	'''Object manager for fstests matrix entities.'''
	__objects = {}
	__objects[Machine] = {}
	__objects[MachineName] = {}
	__objects[TestRun] = {}
	__objects[Test] = {}
	__objects[TestName] = {}
	__objects[Group] = {}
	__objects[GroupMember] = {}
	__objects[ResultType] = {}
	__objects[Result] = {}
	__objects[MachineWithName] = {}
	__objects[Hash] = {}

	@staticmethod
	def find_object(template):
		'''Retrieve an object based on a template.'''
		assert isinstance(template, DatabaseObject)

		try:
			obj_key = template.obj_key()
			return ObjectManager.__objects[type(template)][obj_key]
		except KeyError:
			return None

	@staticmethod
	def store_object(template):
		'''Store an object based on a ... key?'''
		assert isinstance(template, DatabaseObject)

		obj_key = template.obj_key()
		ObjectManager.__objects[type(template)][obj_key] = template

	@staticmethod
	def ensure_object(template):
		r = find_object(template)
		if r is not None:
			return r

		store_object(template)
		return template

# Query support...
class Predicate(object):
	'''Object selector predicate.'''
	pass

class FieldPredicate(Predicate):
	'''Object field selector predicate.'''
	str_ops = set(['=', 'LIKE', '!='])
	num_ops = set(['=', '<=', '>=', '>', '<', '!='])
	def __init__(self, objtype, field, op, value):
		self.objtype = objtype
		self.field = field
		self.op = op
		self.value = value
		self.check([objtype])

	def check(self, types):
		'''Check that this predicate makes sense.'''
		assert self.objtype in types
		assert self.field in self.objtype.fields
		if self.objtype.fields[self.field].type is str:
			assert self.op in self.str_ops
		else:
			assert self.op in self.num_ops

	def sql(self, values, need_table_name = False):
		'''Generate sql for this predicate.'''
		if need_table_name:
			field = '%s.%s' % (self.objtype.table_name, self.field)
		else:
			field = self.field
		values.append(self.objtype.fields[self.field].sql(self.value))
		return '%s %s ?' % (field, self.op)

class PredicateSet(Predicate):
	'''Base class for a set of boolean predicates.'''
	def __init__(self, predicates):
		assert hasattr(self, 'op')
		self.predicates = predicates

	def check(self, types):
		'''Ensure that the predicate set makes sense.'''
		for p in self.predicates:
			p.check(types)

	def sql(self, values, need_table_name = False):
		'''Generate sql for these predicates.'''
		return '(%s)' % self.op.join([x.sql(values, need_table_name) \
				for x in self.predicates])

	def append(self, pred):
		'''Append a predicate.'''
		assert pred is not None

		self.predicates.append(pred)

class OrSet(PredicateSet):
	op = ' OR '

class AndSet(PredicateSet):
	op = ' AND '

class DatabaseQuery(object):
	'''Query the fstests results database.'''
	def __init__(self, db):
		self.db = db

	def __execute(self, sql, values = ()):
		if DEBUG:
			print(sql, values)
		return self.db.conn.execute(sql, values)

	def __create_TestRun_from_results(self, results):
		'''Yield TestRun objects from the query results.'''
		r = results.fetchone()
		while r is not None:
			del r['id']
			t = TestRun(None, **r)
			yield t
			r = results.fetchone()

	def query_test_runs_by_machine_name(self, name, exact = True):
		'''Query test runs by exact machine name.'''
		sql = 'SELECT test_run.* FROM test_run, machine_name WHERE ' \
			'test_run.machine_id = machine_name.machine_id ' \
			'AND machine_name.name %s ?' % \
					('=' if exact else 'LIKE')
		values = (name,)
		results = self.__execute(sql, values)
		return self.__create_TestRun_from_results(results)

	def __yield_objects_from_results(self, results, objtype):
		'''Yield objects from the query results.'''
		r = results.fetchone()
		while r is not None:
			t = objtype(**r)
			yield t
			r = results.fetchone()

	def query_single_table(self, objtype, predicates, attrs = None):
		'''Query a single table or view with the given predicates.'''
		if attrs is None:
			column_str = ', '.join([x for x in objtype.fields])
		else:
			column_str = ', '.join(attrs)
		values = []
		predicates.check([objtype])
		sql = 'SELECT %s FROM %s WHERE %s' % (column_str, \
				objtype.table_name, predicates.sql(values))
		if DEBUG:
			print((sql, values))
		results = self.__execute(sql, values)
		return self.__yield_objects_from_results(results,
				objtype)

	def query_current_test_runs(self, max_age = None):
		'''Return the most recent test runs for each machine.'''

		# SELECT machine_name.name, test_run.start_time,
		# max(test_run.mtime), test_run.kernel, test_run.mount_opts,
		# test_run.mkfs_opts, test_run.run_time, test_run.failed,
		# test_run.skipped, test_run.tried, test_run.counted from
		# test_run, machine_name where machine_name.id =
		# test_run.machine_name_id group by machine_name_id order by
		# test_run.mtime;

		values = ()
		sql = 'SELECT hash.value AS hash, MAX(test_run.mtime) '
		sql += 'FROM test_run, hash WHERE hash.id = test_run.hash_id '
		if max_age is not None:
			sql += 'AND test_run.mtime > ? '
			values += (int(time.time()) - max_age, )
		sql += 'GROUP BY test_run.machine_name_id '
		sql += 'ORDER BY test_run.mtime'
		rows = self.__execute(sql, values)
		for row in rows:
			testrunhash = Hash.resurrect(self.db, value = row['hash'])
			yield TestRun.resurrect(self.db, hash_id = testrunhash)

	def query_test_runs(self):
		'''Return all test runs for all machines.'''

		values = ()
		sql = 'SELECT hash.value AS hash '
		sql += 'FROM test_run, hash WHERE hash.id = test_run.hash_id '
		sql += 'ORDER BY test_run.mtime'
		rows = self.__execute(sql, values)
		for row in rows:
			testrunhash = Hash.resurrect(self.db, value = row['hash'])
			yield TestRun.resurrect(self.db, hash_id = testrunhash)

	def query_failed_tests(self, testrun):
		'''Return all failed tests for a test run.'''

		result_type = ResultType.resurrect(self.db, name = 'fail')

		sql = 'SELECT hash.value AS hash FROM test, result, hash WHERE result.test_run_id = ? AND result.result_type_id = ? AND test.id = result.test_id AND hash.id = test.hash_id'
		values = (getattr(testrun, testrun.db_key), getattr(result_type, result_type.db_key))
		rows = self.__execute(sql, values)
		for row in rows:
			testhash = Hash.resurrect(self.db, value = row['hash'])
			yield Test.resurrect(self.db, hash_id = testhash)

	def query_test_name(self, test):
		'''Try to return the testname of this test.'''
		sql = 'SELECT test_name.name FROM test_name, test WHERE test_name.test_id = ?' #test.id AND test.id = ?'
		values = (getattr(test, test.db_key), )
		rows = self.__execute(sql, values)
		for row in rows:
			yield TestName.resurrect(self.db, name = row['name'])

	@staticmethod
	def construct_ns_map(objtype):
		return {
			objtype.table_name: objtype,
			None: objtype,
		}

	@staticmethod
	def interpret_attrs(attrs, ns_map):
		'''Construct a list of attributes for a query string.'''
		def i(tok):
			nonlocal names, attr_list

			if DEBUG:
				print(tok)
			if tok.type == tokenize.NAME:
				assert len(names) < 2
				names.append(tok.string)
			elif tok.type == tokenize.STRING:
				assert len(names) < 2
				names.append(tok.string[1:-1])
			elif tok.type == tokenize.NEWLINE or \
			     (tok.type == tokenize.OP and tok.string == ',') and \
			     len(names) > 0:
				if len(names) > 1:
					objtype = ns_map[names[0]]
					field = names[1]
				else:
					objtype = ns_map[None]
					field = names[0]
				assert field in objtype.fields
				attr_list.append('.'.join(names))
				names = []
		names = []
		attr_list = []
		ioh = io.BytesIO(attrs.encode('utf-8'))
		for tok in tokenize.tokenize(ioh.readline):
			try:
				i(tok)
			except Exception as e:
				l = tok.end[1] - tok.start[1]
				c = '%s%s' % (' ' * tok.start[1], '^' * l)
				whine = 'Error in attribute list before:\n%s\n%s\n%s' % \
						(attrs, c, '\n'.join(e.args))
				e.args = [whine]
				e.tok = tok
				raise
		return attr_list

	@staticmethod
	def interpret_predicates(query, ns_map):
		'''Construct a set of predicates from a query string.'''
		def op_ok(op):
			uop = op.upper()
			return len(name_parts) > 0 and \
			     (uop in FieldPredicate.str_ops or \
			      uop in FieldPredicate.num_ops)
		def i(tok):
			nonlocal predicates, name_parts, op, level

			if DEBUG:
				print(tok)
			tok_string_lower = tok.string.lower()
			if tok.type == tokenize.ENCODING or \
			   tok.type == tokenize.ENDMARKER:
				return
			elif tok.type == tokenize.NUMBER or \
			     tok.type == tokenize.STRING:
				assert op is not None
				if DEBUG:
					print("name ", name_parts, "op ", op,
							"value ", tok.string)
				if len(name_parts) == 2:
					objtype = ns_map[name_parts[0]]
					field = name_parts[1]
				else:
					objtype = ns_map[None]
					field = name_parts[0]
				if tok.type == tokenize.STRING:
					value = tok.string[1:-1]
				else:
					value = tok.string
				pred = objtype.predicate(field, op, value)
				if predicates[level] is None:
					predicates[level] = pred
				else:
					predicates[level].append(pred)
				name_parts = []
				op = None
			elif tok.type == tokenize.OP and tok.string == '(':
				level += 1
				if DEBUG:
					print("push level %d" % level)
				predicates.append(None)
			elif tok.type == tokenize.OP and tok.string == ')':
				if DEBUG:
					print("pop level %d" % level)
				level -= 1
				if predicates[level] is None:
					predicates[level] = predicates.pop()
				else:
					predicates[level].append(predicates.pop())
			elif tok.type == tokenize.NAME and \
			     tok_string_lower == 'and':
				if DEBUG:
					print("and ", predicates[level])
				predicates[level] = AndSet([predicates[level]])
			elif tok.type == tokenize.NAME and \
			     tok_string_lower == 'or':
				if DEBUG:
					print("or ", predicates[level])
				predicates[level] = OrSet([predicates[level]])
			elif tok.type == tokenize.NAME and \
			     tok_string_lower == 'like' and \
			     op_ok(tok_string_lower):
				assert len(name_parts) > 0
				op = 'LIKE'
				if DEBUG:
					print("name ", name_parts, "op ", op)
			elif tok.type == tokenize.NAME:
				assert len(name_parts) < 2
				name_parts.append(tok.string)
				if DEBUG:
					print("name ", name_parts)
			elif tok.type == tokenize.OP and tok.string == '.':
				assert len(name_parts) == 1
			elif tok.type == tokenize.OP and \
			     tok.string == '==' and \
			     op_ok('='):
				op = '='
				if DEBUG:
					print("name ", name_parts, "op ", op)
			elif tok.type == tokenize.OP and op_ok(tok.string):
				op = tok.string
				if DEBUG:
					print("name ", name_parts, "op ", op)

		predicates = [None]
		name_parts = []
		op = None
		level = 0

		ioh = io.BytesIO(query.encode('utf-8'))
		for tok in tokenize.tokenize(ioh.readline):
			try:
				i(tok)
			except BaseException as e:
				l = tok.end[1] - tok.start[1]
				c = '%s%s' % (' ' * tok.start[1], '^' * l)
				whine = 'Error in query before:\n%s\n%s\n%s' % \
						(query, c, '\n'.join(e.args))
				e.args = [whine]
				raise
		return predicates[0]

