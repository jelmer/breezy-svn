bzr-svn frequently asked questions
==================================

.. contents::

Cloning a large Subversion branch is very slow
----------------------------------------------
There is no way around this at the moment, because Bazaar has to import all
the history from the Subversion branch.

bzr-svn will work significantly faster against a Subversion 1.5 server, so if
you have control over the server it may be worthwhile to upgrade it.

In the future it should hopefully be possible to use stacked branches.

The Bazaar revnos differ from the Subversion revnos
---------------------------------------------------
That's right. Bazaar revision numbers are per-branch, whereas Subversion
revnos are per-repository. If you would like to use Subversion revision
numbers, use the "svn:" revision specifier. For example:

::

  $ bzr ls -rsvn:34 svn://example.com/bar

bzr log will also show the Subversion revision number.

Is it possible to keep the author name when pushing changes into Subversion?
----------------------------------------------------------------------------
Yes, but this requires the repository to allow revision property changes.

See hooks/pre-revprop-change in the Subversion repository for
more information about how to do this.

You also need to enable support for this in bzr-svn by setting
``override-svn-revprops`` in ~/.bazaar/bazaar.conf to a comma-separated
list of Subversion revision properties you would like to override.

For example::

  override-svn-revprops = svn:log, svn:author

Is it possible to not use the on-disk cache?
--------------------------------------------

Yes, simply set ``use-cache = False`` for the repository in question in
~/.bazaar/subversion.conf.  This will of course have some consequences for the
performance of bzr-svn since it will have to re-fetch data.

Is it possible to access/modify custom Subversion file properties?
------------------------------------------------------------------

No, this is not possible. If you are in a native Subversion Working Copy, you
can of course use the "svn propset" and "svn propget" commands.

On Windows, why do I get a ``Access denied`` error for a file with a path ending in \Temp\subvertpy.tmp ?
---------------------------------------------------------------------------------------------------------

If you're getting an error similar to this one::

   bzr: ERROR: [Errno 5] Can't open 'C:\DOCUME~1\MyUsername\LOCALS~1\Temp\subvertpy.tmp': Access is denied.

This is caused by your virus scanner trying to open the temporary file that bzr-svn has created and
accessing it before bzr-svn with an exclusive lock.

..
	vim: ft=rest
