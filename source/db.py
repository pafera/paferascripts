import datetime
import sqlite3
import logging 
import re
import dateutil.parser
import json
import threading
import random

from possumtypes import *

# =====================================================================
def KeyFromValue(ls, value):
	return ls.keys()[ls.values().index(value)]

# *********************************************************************
class DB(object):
	
	LANGUAGES	=	{
		1:	('en_US', 'English (United States)'),
	}
	
	DBTYPES	=	{
		'SQLITE':			1,
		'MYSQL':			2,
		'POSTGRESQL':	3,
	}
	
	CONNECTIONS	=	{}
	DEFAULTCONN	=	None
	DEFAULTFILE	=	None
	
	# ----------------------------------------------------------------------------------------
	def __init__(self, 
			connectionname	=	None,
			dbname					=	None, 
			dbtype 					= 'SQLITE',
			username				=	None,
			password				=	None
		):
		if not connectionname and not dbname:
			connectionname	=	'default'
			dbname					=	DB.DEFAULTFILE
		
		if dbtype == 'SQLITE':
			self.dbconn	=	sqlite3.connect(dbname, 30)
			self.dbconn.row_factory = sqlite3.Row
			self.dbconn.execute("PRAGMA busy_timeout = 15000")
		else:
			raise Exception('Database type {} not supported'.format(dbtype))
		
		self.debug		=	False
		self.language	=	1
		self.objtypes	=	{}
		self.cursor		=	self.dbconn.cursor()
		
		self.connectionname	=	connectionname
		
		DB.CONNECTIONS[connectionname]	=	(dbname, dbtype, self)
		
		if not DB.DEFAULTCONN:
			DB.DEFAULTCONN	=	self
		
		if not self.HasTable('objtypes'):
			self._CreateTables()
			
	# ----------------------------------------------------------------------------------------
	def FindType(self, obj):
		table	=	obj._Table()
		
		if not self.objtypes:
			for r in self.cursor.execute("SELECT * FROM objtypes"):
				self.objtypes[r['id']]	=	(r['classname'], r['tablename'])
		
		for k, v in self.objtypes.items():
			if v[1] == table:
				return k
		
		try:
			r	=	self.Query("SELECT id FROM objtypes WHERE tablename = ?", [table])
			
			if r:
				self.objtypes[r['id']]	=	(obj.__class__.__name__, table)
				return r['id']
					
			self.Query(
				"INSERT INTO objtypes(classname, tablename) VALUES(?, ?)",
				[obj.__class__.__name__, table]
			)
			
			typeid	=	self.cursor.lastrowid
			self.objtypes[typeid]	=	(obj.__class__.__name__, table)
		except Exception as e:
			self.cursor.rollback()
			
		return typeid
		
	# ----------------------------------------------------------------------------------------
	def Debug(self, state	=	True):
		self.debug	=	state
		
	# ----------------------------------------------------------------------------------------
	def Query(self, query, params	=	None):		
		if params == None:
			params	=	[]
			
		if not isinstance(params, list) and not isinstance(params, tuple):
			params	=	(params,)
			
		if self.debug:
			Print('DB: Executing query: {} with params {}', query, params)
		
		results	=	self.cursor.execute(query, params).fetchall()
		
		if self.debug:
			for r in results:
				Print('DB: Results: {}', dict(zip(r.keys(), r)))
		
		return results
		
	# ----------------------------------------------------------------------------------------
	def HasTable(self, table):
		try:
			self.Query("SELECT * FROM {} LIMIT 1".format(table))
			return True
		except Exception as e:
			return False
		
	# ----------------------------------------------------------------------------------------
	def Begin(self):
		self.dbconn.execute("BEGIN TRANSACTION")
		
	# ----------------------------------------------------------------------------------------
	def Commit(self):
		self.dbconn.commit()
		
	# ----------------------------------------------------------------------------------------
	def Rollback(self):
		self.dbconn.rollback()
		
	# ----------------------------------------------------------------------------------------
	@staticmethod
	def Date(timestamp	=	None):
		if timestamp != None:
			d	=	datetime.datetime.utcfromtimestamp(timestamp)
		else:
			d	=	datetime.datetime.utcnow()
		return d.isoformat()
		
	# ----------------------------------------------------------------------------------------
	def _CreateTables(self):
		with self.dbconn as conn:
			cur	=	conn.cursor()
			cur.executescript("""
				CREATE TABLE links(
					type1		INT NOT NULL,
					id1			INT NOT NULL,
					type2		INT NOT NULL,
					id2			INT NOT NULL,
					type		INT,
					num			INT,
					comment	TEXT,
					PRIMARY KEY(type1, id1, type2, id2)
				);
				CREATE TABLE translations(
					id				INTEGER PRIMARY KEY,
					textid		INTEGER,
					language	INT NOT NULL,
					text			TEXT NOT NULL
				);
				CREATE TABLE objtypes(
					id				INTEGER PRIMARY KEY,
					classname	TEXT NOT NULL,
					tablename	TEXT NOT NULL
				);
				CREATE TABLE dbconfig(
					id				INTEGER PRIMARY KEY,
					key				TEXT NOT NULL,
					value			TEXT NOT NULL
				);
				"""
			)
		
	# ------------------------------------------------------------------
	def __getitem__(self, key, value = None):
		r	=	self.Query("SELECT value FROM dbconfig WHERE key = ?", [key])
		
		if value == None:			
			if r:
				return r[0]['value']
				
		return None
		
	# ------------------------------------------------------------------
	def __setitem__(self, key, value):
		r	=	self.Query("SELECT value FROM dbconfig WHERE key = ?", [key])
		
		if r:
			self.Query("UPDATE dbconfig SET value = ? WHERE key = ?", [value, key])
		else:
			self.Query("INSERT INTO dbconfig(key, value) VALUES(?, ?)", [key, value])
		
	# ------------------------------------------------------------------
	# Delete orphaned links
	def TidyLinks(self):
		numtidied	=	0
		
		try:
			with self.dbconn as conn:
				cur	=	conn.cursor()
				for r in cur.execute("SELECT type1, id1, type2, id2 FROM links"):
					r	=	cur.execute("SELECT id FROM {self.objtypes[r['type1']][1]} WHERE id = {r['id1']}".format(**locals()))
					
					if not r:
						numtidied	+=	1
						conn.execute("""DELETE FROM links 
							WHERE type1 = {r['type1']} 
								AND id1 = {r['id1']}
								AND type2 = {r['type2']} 
								AND id2 = {r['id2']}""".format(**locals()))

					r	=	cur.execute("SELECT id FROM {self.objtypes[r['type2']][1]} WHERE id = {r['id2']}")
					
					if not r:
						numtidied	+=	1
						conn.execute("""DELETE FROM links 
							WHERE type1 = {r['type1']} 
								AND id1 = {r['id1']}
								AND type2 = {r['type2']} 
								AND id2 = {r['id2']}""".format(**locals()))
		except Exception as e:
			logging.warning('Unable to tidy links: {}'.format(e))
			return -1
		
		return numtidied
		
	# ------------------------------------------------------------------
	def Translate(self, textid, vardict	=	None):
		if vardict == None:
			vardict	=	{}
			
		t	=	self.Query(
			"SELECT text FROM translations WHERE textid = ? AND language = ?", 
			(textid, self.language)
		)
		
		if not t:
			return ''
		
		if vardict:
			t	=	t.format(vardict)		
			
		return t
		
	# ------------------------------------------------------------------
	def SetTranslation(language, text, id):
		maxid	=	0
		
		if id:
			r	=	self.Query("""SELECT textid FROM translations 
				WHERE language = ? AND textid = ?""",
				(language, id)
			)
			
			if r:
				self.Query("UPDATE translations SET text = ? WHERE textid = ? AND language = ?", 
					(text, id, language)
				)
			else:
				self.Query("INSERT INTO translations VALUES(?, ?, ?)", 
					(id, language, text)
				)
			return id
		else:
			r	=	self.Query(
				'SELECT textid FROM translations WHERE language = ? AND text = ?',
				(language, text)
			)
			
			if r:
				return r[0]['textid']
			
			r	=	self.Query('SELECT MAX(textid) FROM translations')
			
			maxid	=	int(r[0]['MAX(textid)']) + 1 if r else 1
			self.Query("INSERT INTO translations VALUES(?, ?, ?)", (maxid, language, text))
		
		return maxid
		
	# ------------------------------------------------------------------
	def UpdateTable(self, model):
		fields			=	['id INTEGER PRIMARY KEY']
		fieldnames	=	['id']
		
		for k, v in model.FIELDS.items():
			fields.append(k + ' ' + v[0])
			fieldnames.append(k)
		
		fields			=	', '.join(fields)
		fieldnames	=	', '.join(fieldnames)
		
		with self.dbconn as conn:
			conn.executescript("""
				CREATE TABLE temptable({fields});
				INSERT INTO temptable({fieldnames}) SELECT {fieldnames} FROM {model.TABLE};
				DROP TABLE {model.TABLE};
				ALTER TABLE temptable RENAME TO {model->TABLE};""".format(**locals())
			)

# *********************************************************************
class BaseValidator(object):
	pass

# *********************************************************************
class FakeValidator(BaseValidator):
	def Validate(self, fieldname, value):	
		pass

# *********************************************************************
class NullValidator(BaseValidator):
	def Validate(self, fieldname, value):	
		if value == None:
			raise Exception('{} cannot be None!'.format(fieldname))
		
# *********************************************************************
class EmailValidator(BaseValidator):
	def Validate(self, fieldname, value):	
		if not re.match(r"/[a-z0-9!#%&'*+/=?^_`{|}~-]+(?:\.[a-z0-9!#%&'*+/=?^_`{|}~-]+)*@(?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)+[a-z0-9](?:[a-z0-9-]*[a-z0-9])?/i", value):
			raise Exception('{} is not a valid email address!'.format(value))

# *********************************************************************
class DateValidator(BaseValidator):
	def Validate(self, fieldname, value):	
		try:
			datetime.date.strptime('%Y-%m-%d')
		except:
			raise Exception('{} is not a valid date!'.format(value))
			
# *********************************************************************
class TimeValidator(BaseValidator):
	def Validate(self, fieldname, value):	
		try:
			datetime.time.strptime('%H:%M:%S')
		except:
			raise Exception('{} is not a valid date!'.format(value))
			
# *********************************************************************
class DateTimeValidator(BaseValidator):
	def Validate(self, fieldname, value):	
		try:
			datetime.datetime.strptime('%Y-%m-%dT%H:%M:%S')
		except:
			raise Exception('{} is not a valid date!'.format(value))

# *********************************************************************
class RangeValidator(BaseValidator):
	
	# -------------------------------------------------------------------
	def __init__(self, min, max):
		self.min	=	min
		self.max	=	max
		
	# -------------------------------------------------------------------
	def Validate(self, fieldname, value):	
		if value < self.min:
			raise Exception('{} is too low!'.format(value))
			
		if value > self.max:
			raise Exception('{} is too high!'.format(value))

# *********************************************************************
class ModelBase(object):
	
	# -------------------------------------------------------------------
	def __init__(self, db	=	None):
		if db:
			self._db	=	db
		
		self._InitFields()
	
	# -------------------------------------------------------------------
	def _DB(self):
		return self._db if hasattr(self, '_db') else DB.DEFAULTCONN
		
	# -------------------------------------------------------------------
	def _Table(self):
		return self._table if hasattr(self, '_TABLE') else self.__class__.__name__.lower()
		
	# -------------------------------------------------------------------
	def __hash__(self):
		return self.id if self.id else 0
		
	# -------------------------------------------------------------------
	def __eq__(self, o):
		return (self.__class__ ==  o.__class__) and (self.id == o.id) and (self.id and o.id)
		
	# -------------------------------------------------------------------
	def __cmp__(self, o):
		sid	=	self.id if self.id else 0
		oid	=	o.id if o.id else 0
		return oid - sid
		
	# -------------------------------------------------------------------
	def CreateTable(self):
		conn	=	self._DB()
		table	=	self._Table()
		
		if conn.HasTable(table):
			return
			
		fields	=	['id INTEGER PRIMARY KEY AUTOINCREMENT']
		
		for k, v in self._fields.items():
			if v[0] == 'JSON':
				fields.append('{} TEXT {}'.format(k, v[1]))
			else:
				fields.append('{} {} {}'.format(k, v[0], v[1]))
		
		fields	=	', '.join(fields)
		
		conn.Query("CREATE TABLE {table}({fields})".format(**locals()))
		
		if hasattr(self, '_indexes'):
			for k, v in self._indexes.items():
				conn.Query("CREATE INDEX {k} ON {table}({v})".format(**locals()))
		
		return self
		
	# ------------------------------------------------------------------
	def _ImportFields(self, fields):
		for k in self._fields.keys():
			if k in fields.keys():
				setattr(self, k, fields[k])
				
	# ------------------------------------------------------------------
	def _InitFields(self):
		self.id	=	None
		
		for k, v in self._fields.items():
			if 'NOT NULL' in v[1] and (v[0] == 'INT' or v[0] == 'FLOAT'):
				setattr(self, k, 0)
			elif v[0] == 'DATETIME':
				setattr(self, k, DB.Date(0))
			else:
				setattr(self, k, None)
	
	# ------------------------------------------------------------------
	def _ConvertFields(self, fields):
		self.id	=	fields['id']
		
		if not self.id:
			raise Exception('No {} with ID {} was found.'.format(
				self.__class__.__name__, 
				fields['id'])
			)
			
		for k, v in self._fields.items():
			if k not in fields.keys():
				setattr(self, k, None)
				continue
			
			if fields[k] != None:
				if v[0] == 'INT':
						setattr(self, k, int(fields[k]))
				elif v[0] == 'FLOAT':
					setattr(self, k, float(fields[k]))
				elif v[0] == 'JSON':
					setattr(self, k, json.loads(fields[k]))
				else:
					setattr(self, k, fields[k])
			else:
				setattr(self, k, fields[k])
				
	# ------------------------------------------------------------------
	def Count(self, cond = '', params = None):
		if params == None:
			params	=	[]
			
		try:
			r	=	self._DB().Query("SELECT COUNT(*) FROM {} {}".format(self._Table(), cond), params)
			
			if r:
				return r[0]['COUNT(*)']
		except Exception as e:
			if 'no such table' in str(e):
				self.CreateTable()
				return 0
			raise e
		
		return 0
		
	# ------------------------------------------------------------------
	def Load(self, id, fields = '*'):
		if not id:
			raise Exception('Cannot load {} with no ID'.format(self.__class__.__name__))
			
		conn	=	self._DB()
		table	=	self._Table()
		
		r	=	conn.Query("SELECT {fields} FROM {table} WHERE id = ?".format(**locals()), [id])
		
		if r:
			self._ConvertFields(r[0])
		else:
			raise Exception('{} with ID {} was not found.'.format(self.__class__.__name__, id))
			
		return self
	
	# ------------------------------------------------------------------
	def Find(self, cond = '', params = None, fields = '*'):
		if params == None:
			params	=	[]
			
		conn	=	self._DB()
		table	=	self._Table()
		ls	=	[]
		
		try:
			for r in conn.Query("SELECT {fields} FROM {table} {cond}".format(**locals()), params):
				o	=	self.__class__()
				o._db	=	conn
				o._ConvertFields(r)
				ls.append(o)
		except Exception as e:
			if 'no such table' in str(e):
				self.CreateTable()
			else:
				raise e
		
		return ls
	
	# ------------------------------------------------------------------
	def New(self, **kwargs):
		conn	=	self._DB()
		table	=	self._Table()
		
		obj	=	self.__class__()
		
		for k in self._fields.keys():
			if k in kwargs.keys():
				setattr(obj, k, kwargs[k])
			else:
				setattr(obj, k, None)
		
		obj.Save()
		
		return obj

	# ------------------------------------------------------------------
	def Save(self):
		conn	=	self._DB()
		table	=	self._Table()
		
		keys	=	self._fields.keys()	
		fieldnames		=	', '.join(self._fields.keys())
		placeholders	=	', '.join(['?' for i in range(0, len(keys))])
		fields				=	[]
		
		for k, v in self._fields.items():
			if v[0] == 'JSON':
				fields.append(json.dumps(getattr(self, k), True))
			elif v[0] == 'JSON':
				if isinstance(getattr(self, k), datetime):
					fields.append(getattr(self, k).isoformat())
				else:
					fields.append(getattr(self, k))
			else:
				fields.append(getattr(self, k))
			
			v[2].Validate(k, fields[-1])
		
		if not self.id:
			query	=	"INSERT INTO {table}({fieldnames}) VALUES({placeholders})".format(**locals())
			
			try:
				conn.Query(query, fields)
			except Exception as e:
				if 'no such table' in str(e):
					self.CreateTable()
					conn.Query(query, fields)
				else:
					raise e
				
			self.id	=	conn.cursor.lastrowid
			return self.id
		else:
			pairs	=	[]
			
			for k in self._fields.keys():
				pairs.append(k + ' = ?')
			
			pairs	=	', '.join(pairs)
			
			conn.Query(
				"UPDATE {table} SET {pairs} WHERE id = {self.id}".format(**locals()), 
				fields
			)
			return self.id
	
	# ------------------------------------------------------------------
	def Delete(self, cond = '', params = None):
		if not params:
			params	=	{}
			
		conn	=	self._DB()
		table	=	self._Table()
		
		if not cond:
			conn.Query("DELETE FROM {table} WHERE id = ?".format(**locals()), [self.id])
			type1	=	conn.FindType(self)
			conn.Query("""DELETE FROM links 
				WHERE (type1 = ? AND id1 = ?)
					OR (type2 = ? AND id2 = ?)""",
				[type1, self.id, type1, self.id]
			)
			self.id	=	None
		else:
			conn.Query("DELETE FROM {table} {cond}".format(**locals()), params)
	
	# ------------------------------------------------------------------
	def Link(self, obj, type = 0, num = 0, comment = None):
		if isinstance(obj, list):
			return self.LinkList(obj, type, comment)
		
		if not self.id or not obj.id:
			raise Exception('Cannot link uninitialized objects.')
			
		conn	=	self._DB()
		
		type1	=	conn.FindType(self)
		type2	=	conn.FindType(obj)
		
		if type1 > type2:
			t			=	type1
			type1	=	type2
			type2	=	t
			id1		=	obj.id
			id2		=	self.id
		else:
			id1		=	self.id
			id2		=	obj.id
		
		r	=	conn.Query(
			"SELECT num FROM links WHERE type1 = ? AND type2 = ? AND id1 = ? AND id2 = ? AND type = ?", 
			[type1, type2, id1, id2, type]
		)
		
		if not r:
			conn.Query(
				'INSERT INTO links(type1, id1, type2, id2, type, num, comment) VALUES(?, ?, ?, ?, ?, ?, ?)', 
				[type1, id1, type2, id2, type, num, comment]
			)
		else:
			if r['num'] != num or r['comment'] != comment:
				conn.Query(
					'UPDATE links SET num = ?, comment = ? WHERE type1 = ? AND id1 = ? AND type2 = ? AND id2 = ? AND type = ?', 
					[num, comment, type1, id1, type2, id2, type]
				)
		
		return self

	# ------------------------------------------------------------------
	def LinkList(self, ls, type = 0, comment = None):
		if not len(ls):
			return
			
		if not self.id:
			raise Exception('Cannot link uninitialized objects.')
		
		conn	=	self._DB()
		
		type1	=	conn.FindType(self)
		type2	=	conn.FindType(ls[0])
		
		if type1 > type2:
			conn.Query(
				"DELETE FROM links WHERE type1 = ? AND type2 = ? AND id2 = ? AND type = ?",
				[type2, type1, self.id, type]
			)
		else:
			conn.Query(
				"DELETE FROM links WHERE type1 = ? AND type2 = ? AND id1 = ? AND type = ?",
				[type1, type2, self.id, type]
			)
		
		num	=	0
		
		for v in ls:
			if not v.id:
				raise Exception('Cannot link uninitialized objects.')
				 
			if type1 > type2:
				conn.Query(
					"""INSERT INTO links(type1, id1, type2, id2, type, num, comment) 
					VALUES(?, ?, ?, ?, ?, ?, ?)""", 
					[type2, v.id, type1, self.id, type, num, comment]
				)
			else:
				conn.Query(
					"""INSERT INTO links(type1, id1, type2, id2, type, num, comment) 
					VALUES(?, ?, ?, ?, ?, ?, ?)""", 
					[type1, self.id, type2, v.id, type, num, comment]
				)
			
			num	+=	1
		
		return self
	
	# ------------------------------------------------------------------
	def Unlink(self, obj, type = 0):
		if not self.id or not obj.id:
			raise Exception('Cannot unlink uninitialized objects.')
		
		conn	=	self._DB()
		type1	=	conn.FindType(self)
		type2	=	conn.FindType(obj)
		
		if type1 > type2:
			t			=	type1
			type1	=	type2
			type2	=	t
			id1		=	obj.id
			id2		=	self.id
		else:
			id1		=	self.id
			id2		=	obj.id
			
		if type:
			conn.Query(
				"""DELETE FROM links WHERE type1 = ? AND id1 = ? AND type2 = ? 
				AND id2 = ? AND type = ?""", 
				[type1, id1, type2, id2, type]
			)
		else:
			conn.Query("""DELETE FROM links WHERE type1 = ? AND id1 = ? 
				AND type2 = ? AND id2 = ?""", 
				[type1, id1, type2, id2]
			)
		
		if type1 == type2:
			conn.Query(
				"""DELETE FROM links WHERE type1 = ? AND id1 = ? 
				AND type2 = ? AND id2 = ? AND type = ?""", 
				[type1, id2, type2, id1, type]
			)
			
		return self
	
	# ------------------------------------------------------------------
	def Linked(self, obj, type = 0, fields = '*'):
		if not self.id:
			raise Exception('Cannot find links to an uninitialized object.')
		
		conn	=	self._DB()
		type1	=	conn.FindType(self)
		type2	=	conn.FindType(obj)
		
		objs	=	[]
		
		if type1 > type2:
			query	=	"""SELECT id1 AS id, num FROM links 
				WHERE type1 = ? AND type2 = ? AND id2 = ? AND type = ?
				ORDER BY num"""
			params	=	[type2, type1, self.id, type]
		else:
			query	=	"""SELECT id2 AS id, num FROM links 
				WHERE type1 = ? AND type2 = ? AND id1 = ? AND type = ?
				ORDER BY num"""
			params	=	[type1, type2, self.id, type]
		
		for r in conn.Query(query, params):
			try:
				o	=	obj.__class__(db = conn)
				o.Load(r['id'], fields)
			except Exception as e:
				logging.warning(
					"No {} with ID {} was found: {}".format(
						obj.__class__.__name__, r['id'], e
					)
				)
				continue
			
			if r['num']:
				objs[r['num']]	=	o
			else:
				objs.append(o)
		
		if type1 == type2:
			for r in conn.Query(
				"""SELECT id1, num FROM links 
				WHERE type1 = ? AND type2 = ? AND id2 = ? AND type = ?
				ORDER BY num""",
				[type1, type2, self.id, type]
			):
				o	=	obj.__class__(r['id'], fields)
				o._db	=	self._db
				
			if r['num']:
				objs[r['num']]	=	o
			else:
				objs.append(o)
		
		return objs

	# ------------------------------------------------------------------
	def Debug(self):
		ls	=	[]
		
		for k, v in self._fields.items():
			ls.append("\t{}:\t{}".format(k, getattr(self, k)))
		
		return "class {} with attributes\n\t{}".format(
			self.__class__.__name__,
			'\n'.join(ls)
		)

	# ------------------------------------------------------------------
	def MaxID(self):
		conn	=	self._DB()
		r	=	conn.Query("SELECT MAX(id) FROM {this,TABLE}")
		
		if r:
			return int(r[0]['MAX(id)'])
		
		return 0

	# ------------------------------------------------------------------
	def Translate(self, attr):
		conn	=	self._DB()
		return conn.Translate(getattr(self, attr + id)) if self.id else ''
		
	# -------------------------------------------------------------------
	def Commit(self):
		self._DB().Commit()
		
	# -------------------------------------------------------------------
	def Rollback(self):
		self._DB().rollback()

# *********************************************************************
class DBList(object):
		
	# -------------------------------------------------------------------
	def __init__(self, obj):
		super(DBList, self).__init__()
		
		self.obj				=	obj
		self.filter			=	''
		self.params			=	[]
		self.orderby		=	''
		self.randompos	=	0
		self.pos				=	0
		self.length			=	0
		self.cachepos		=	0
		self.cache			=	[]
		self.cachesize	=	32
		self.randomlist	=	[]
		
	# -------------------------------------------------------------------
	def __iter__(self):
		self.pos	=	-1
		return self
		
	# -------------------------------------------------------------------
	def next(self):
		if self.pos < self.length:
			self.pos	+=	1
		else:
			raise StopIteration
			
		return self[self.pos]
		
	# -------------------------------------------------------------------
	def Count(self):
		if self.filter:
			self.length	=	self.obj.Count(self.filter, self.params)
		else:
			self.length	=	self.obj.Count()
			
		return self.length
		
	# -------------------------------------------------------------------
	def Filter(self, condition, params):
		self.filter	=	condition
		self.params	=	params
		self.cache	=	[]
		self.Count()
		return self
		
	# -------------------------------------------------------------------
	def OrderBy(self, order):
		self.orderby	=	order
		self.cache		=	[]
		self.Count()
		return self
		
	# -------------------------------------------------------------------
	def __len__(self):
		if not self.cache:
			self.Count()
		
		return self.length
		
	# -------------------------------------------------------------------
	def __getitem__(self, pos):
		if self.randomlist:
			self.randompos	=	self.randomlist[pos]
			self._RefreshCache(self.randompos)
			return self.cache[0]
		
		if not self.cache or pos < self.cachepos or pos > self.cachepos + len(self.cache) - 1:
			self._RefreshCache(pos)
		
		return self.cache[pos - self.cachepos]
		
	# -------------------------------------------------------------------
	def __delitem__(self, pos):
		if self.randomlist:
			self.randompos	=	self.randomlist[pos]
			self._RefreshCache(self.randompos)
			self.cache[self.randompos - self.cachepos].Delete()
			del self.cache[self.randompos - self.cachepos]
			self.length	-=	1
			return self
		
		if not self.cache or pos < self.cachepos or pos > self.cachepos + len(self.cache) - 1:
			self._RefreshCache(pos)
		
		self.cache[pos - self.cachepos].Delete()
		del self.cache[pos - self.cachepos]
		self.length	-=	1
		return self
		
	# -------------------------------------------------------------------
	def _RefreshCache(self, pos):
		query	=	''
		
		if self.filter:
			query	=	query + self.filter
			
		if self.orderby:
			query	=	query + ' ORDER BY ' + self.orderby
		
		if self.randomlist:
			query	=	query + ' LIMIT {}, 1'.format(pos)
		else:
			query	=	query + ' LIMIT {}, {}'.format(pos, self.cachesize)
		
		self.cache		=	self.obj.Find(query, self.params)
		self.cachepos	=	pos
		
	# -------------------------------------------------------------------
	def SetRandom(self, active):
		if active:
			self.randomlist	=	list(range(0, self.Count()))
			random.shuffle(self.randomlist)
		else:
			self.randomlist	=	[]
