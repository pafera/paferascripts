#!/usr/bin/python
# -*- coding: utf-8 -*- 

import sys
import subprocess
import inspect

PY2 = sys.version_info[0] == 2
PY3 = sys.version_info[0] == 3

def DefInt(v):
	try:
		return int(v)
	except Exception as e:
		return 0

if PY2:
	def S(v):
		if isinstance(v, unicode):
			return v.encode(sys.getfilesystemencoding())
			
		return str(v)
		
	def U(v):
		if isinstance(v, str):
			return v.decode(sys.getfilesystemencoding())
			
		return unicode(v)
		
	def Print(v, *args):
		print(Printf(v, *args))
		
	def PrintB(v, *args):
		print(S(Printf(v, *args)))
		
	def Printf(v, *args):
		if args:
			if isinstance(args, tuple):
				args	=	[U(a) for a in args]
				return U(v).format(*args)
			else:
				return U(v).format(U(args))
				
		return v
		
	def PrintL(v, localdict = None):
		
		if not localdict:
			localdict	=	inspect.currentframe().f_back.f_locals
		
		print(PrintLf(v, localdict))
		
	def PrintBL(v, localdict = None):
		
		if not localdict:
			localdict	=	inspect.currentframe().f_back.f_locals
		
		print(S(PrintLf(v, localdict)))
		
	def PrintLf(s, localdict	=	None):
		if not localdict:
			localdict	=	inspect.currentframe().f_back.f_locals
			
		udict	=	{}
		
		for k, v in localdict.iteritems():
			if isinstance(v, str):
				udict[k]	=	v.decode(sys.getfilesystemencoding())
			else:
				udict[k]	=	v
			
		return U(s).format(**udict)
		
elif PY3:
	def S(v):
		if not isinstance(v, bytes):
			return bytes(v, sys.getfilesystemencoding())
			
		return v
		
	def U(v):
		if not isinstance(v, str):
			return str(v, sys.getfilesystemencoding())
		
		return v
		
	def Print(v, *args):
		print(Printf(v, *args))
		
	def Printf(v, *args):
		if args:
			if isinstance(args, tuple):
				return v.format(*args)
			else:
				return v.format(args)
				
		return v
		
	def PrintL(v, localdict = None):
		if not localdict:
			localdict	=	inspect.currentframe().f_back.f_locals
			
		print(PrintLf(v, localdict))
		
	def PrintLf(v, localdict = None):
		if not localdict:
			localdict	=	inspect.currentframe().f_back.f_locals
		
		return v.format(**localdict)
		
	def RunCommand(cmdlist):
		cmdlist	=	[U(t) for t in cmdlist]
		return U(subprocess.check_output(cmdlist))
		
	def RunDaemon(cmdlist):
		cmdlist	=	[U(t) for t in cmdlist]
		subprocess.Popen(cmdlist)
