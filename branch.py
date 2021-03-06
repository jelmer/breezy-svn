# Copyright (C) 2005-2009 Jelmer Vernooij <jelmer@samba.org>

# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA


"""Handles branch-specific operations."""

from __future__ import absolute_import

from subvertpy import (
    ERR_FS_NO_SUCH_REVISION,
    NODE_DIR,
    SubversionException,
    wc,
    )

from breezy import (
    tag,
    trace,
    urlutils,
    )
from breezy.branch import (
    Branch,
    BranchFormat,
    BranchCheckResult,
    BranchPushResult,
    BranchWriteLockResult,
    GenericInterBranch,
    InterBranch,
    PullResult,
    UnstackableBranchFormat,
    )
from breezy.controldir import (
    ControlDir,
    format_registry,
    )
from breezy.errors import (
    DivergedBranches,
    InaccessibleParent,
    IncompatibleFormat,
    InvalidRevisionId,
    LocalRequiresBoundBranch,
    LossyPushToSameVCS,
    NoSuchRevision,
    NotBranchError,
    PathNotChild,
    ReadOnlyError,
    TokenLockingNotSupported,
    )
from breezy.foreign import (
    ForeignBranch,
    )
from breezy.lock import (
    LogicalLockResult,
    )
from breezy.revision import (
    NULL_REVISION,
    is_null,
    ensure_null,
    )
from breezy.sixish import (
    text_type,
    )
from breezy.symbol_versioning import (
    deprecated_method,
    deprecated_in,
    )
from breezy.transport import get_transport

from . import (
    util,
    )
from .config import (
    BranchConfig,
    SvnBranchStack,
    )
from .errors import (
    NotSvnBranchPath,
    PushToEmptyBranch,
    SubversionBranchDiverged,
    )
from .fetch import (
    InterFromSvnToInventoryRepository,
    )
from .push import (
    InterToSvnRepository,
    create_branch_with_hidden_commit,
    )
from .tags import (
    SubversionTags,
    resolve_tags_svn_ancestry,
    )
from .transport import (
    bzr_to_svn_url,
    )


class SubversionBranchCheckResult(BranchCheckResult):
    """Result of checking a Subversion branch."""


class SubversionSourcePullResult(PullResult):
    """Subversion source pull result.

    The main difference with a standard Bazaar PullResult is that it also
    reports the Subversion revision number.
    """

    def report(self, to_file):
        if not trace.is_quiet():
            if self.old_revid in (self.new_revid, NULL_REVISION):
                to_file.write('No revisions to pull.\n')
            else:
                if self.new_revmeta is None:
                    self.new_revmeta, _ = self.source_branch.repository._get_revmeta(self.new_revid)
                to_file.write('Now on revision %d (svn revno: %d).\n' %
                        (self.new_revno, self.new_revmeta.metarev.revnum))
        self._show_tag_conficts(to_file)


class SubversionTargetBranchPushResult(BranchPushResult):
    """Subversion target branch push result."""

    def _lookup_revno(self, revid):
        assert isinstance(revid, str), "was %r" % revid
        # Try in source branch first, it'll be faster
        try:
            return self.source_branch.revision_id_to_revno(revid)
        except NoSuchRevision:
            if self.local_branch is not None:
                return self.local_branch.revision_id_to_revno(revid)
            else:
                return self.master_branch.revision_id_to_revno(revid)

    @property
    def old_revno(self):
        try:
            return self._lookup_revno(self.old_revid)
        except NoSuchRevision:
            graph = self.master_branch.repository.get_graph(
                self.source_branch.repository)
            return graph.find_distance_to_null(self.old_revid, [])

    @property
    def new_revno(self):
        return self._lookup_revno(self.new_revid)


class SubversionTargetPullResult(PullResult):
    """Subversion target branch pull result."""

    def _lookup_revno(self, revid):
        # Try in source branch first, it'll be faster
        try:
            return self.source_branch.revision_id_to_revno(revid)
        except NoSuchRevision:
            return self.target_branch.revision_id_to_revno(revid)

    @property
    def old_revno(self):
        try:
            return self._lookup_revno(self.old_revid)
        except NoSuchRevision:
            graph = self.target_branch.repository.get_graph(
                self.source_branch.repository)
            return graph.find_distance_to_null(self.old_revid, [])

    @property
    def new_revno(self):
        return self._lookup_revno(self.new_revid)


class SvnBranch(ForeignBranch):
    """Maps to a Branch in a Subversion repository """

    def __init__(self, repository, controldir, branch_path, mapping,
            revnum=None, project=None, _skip_check=False):
        """Instantiate a new SvnBranch.

        :param repository: SvnRepository this branch is part of.
        :param controldir: Control dir this branch was opened on
        :param branch_path: Relative path inside the repository this
            branch is located at.
        :param revnum: Subversion revision number of the branch to
            look at; none for latest.
        :param _skip_check: If True, don't check if the branch actually exists.
        """
        self.repository = repository
        self.controldir = controldir
        self._format = SvnBranchFormat()
        self.layout = self.repository.get_layout()
        if not isinstance(branch_path, text_type):
            raise TypeError(branch_path)
        self._branch_path = branch_path.strip(u"/")
        self.base = urlutils.join(self.repository.base, urlutils.escape(self._branch_path)).rstrip("/")
        super(SvnBranch, self).__init__(mapping)
        self._lock_mode = None
        self._lock_count = 0
        self._clear_cached_state()
        if not _skip_check:
            try:
                if self.check_path() != NODE_DIR:
                    raise NotBranchError(self.base)
            except SubversionException, (_, num):
                if num == ERR_FS_NO_SUCH_REVISION:
                    raise NotBranchError(self.base)
                raise
        if project is None:
            try:
                project = self.layout.get_branch_project(branch_path)
            except NotSvnBranchPath:
                raise NotBranchError(branch_path)
        assert isinstance(project, text_type)
        self.project = project
        self.name = self.layout.get_branch_name(branch_path)

    @property
    def user_transport(self):
        return self.repository.transport.clone(self.get_branch_path())

    @property
    def control_transport(self):
        return self.repository.transport.clone(self.get_branch_path())

    def leave_lock_in_place(self):
        raise NotImplementedError(self.leave_lock_in_place)

    def dont_leave_lock_in_place(self):
        raise NotImplementedError(self.dont_leave_lock_in_place)

    def _push_should_merge_tags(self):
        return self.supports_tags()

    def check_path(self):
        return self.repository.svn_transport.check_path(self._branch_path,
            self.repository.get_latest_revnum())

    def supports_tags(self):
        """See Branch.supports_tags()."""
        return (self._format.supports_tags() and
                self.mapping.supports_tags() and
                self.layout.supports_tags())

    def set_branch_path(self, branch_path):
        """Change the branch path for this branch.

        :param branch_path: New branch path.
        """
        self._branch_path = branch_path.strip("/")

    def get_branch_path(self, revnum=None):
        """Find the branch path of this branch in the specified revnum.

        :param revnum: Revnum to look for.
        """
        if revnum is None:
            return self._branch_path

        assert revnum >= 0

        last_revmeta, _ = self.last_revmeta(skip_hidden=False)
        if revnum > last_revmeta.metarev.revnum:
            # Apparently a commit happened in the mean time
            self._clear_cached_state()
            last_revmeta, _ = self.last_revmeta(skip_hidden=False)
        if revnum == last_revmeta.metarev.revnum:
            return last_revmeta.metarev.branch_path

        locations = self.repository.svn_transport.get_locations(
                last_revmeta.metarev.branch_path, last_revmeta.metarev.revnum,
                [revnum])

        # Use revnum - this branch may have been moved in the past
        return locations[revnum].strip("/")

    def get_revnum(self):
        """Obtain the Subversion revision number this branch was
        last changed in.

        :return: Revision number
        """
        return self.last_revmeta(skip_hidden=False)[0].metarev.revnum

    def get_child_submit_format(self):
        """Return the preferred format of submissions to this branch."""
        ret = self.get_config().get_user_option("child_submit_format")
        if ret is not None:
            return ret
        return "svn"

    def last_revmeta(self, skip_hidden):
        """Return the revmeta element for the last revision in this branch.

        :param skip_hidden: Whether to skip hidden revisions
        """
        for revmeta, hidden, mapping in self._revision_meta_history():
            if hidden and skip_hidden:
                continue
            return revmeta, mapping
        return None, None

    def check(self, refs=None):
        """See Branch.Check.

        Doesn't do anything for Subversion repositories at the moment (yet).
        """
        # TODO: Check svn file properties?
        return SubversionBranchCheckResult(self)

    def _create_heavyweight_checkout(self, to_location, revision_id=None,
                                     hardlink=False):
        """Create a new heavyweight checkout of this branch.

        :param to_location: URL of location to create the new checkout in.
        :param revision_id: Revision that should be the tip of the checkout.
        :param hardlink: Whether to hardlink
        :return: WorkingTree object of checkout.
        """
        checkout_branch = ControlDir.create_branch_convenience(
            to_location, force_new_tree=False,
            format=self._get_checkout_format(lightweight=False))
        checkout = checkout_branch.controldir
        checkout_branch.bind(self)
        # pull up to the specified revision_id to set the initial
        # branch tip correctly, and seed it with history.
        checkout_branch.pull(self, stop_revision=revision_id)
        return checkout.create_workingtree(revision_id, hardlink=hardlink)

    def lookup_bzr_revision_id(self, revid):
        """Look up the matching Subversion revision number on the mainline of
        the branch.

        :param revid: Revision id to look up.
        :return: Tuple with foreign revision id and mapping
        :raises NoSuchRevision: If the revision id was not found.
        """
        return self.repository.lookup_bzr_revision_id(revid,
            ancestry=(self.get_branch_path(), self.get_revnum()),
            project=self.project)

    def _create_lightweight_checkout(self, to_location, revision_id=None):
        """Create a new lightweight checkout of this branch.

        :param to_location: URL of location to create the checkout in.
        :param revision_id: Tip of the checkout.
        :return: WorkingTree object of the checkout.
        """
        from .workingtree import (
            SvnCheckout,
            SvnWorkingTreeDirFormat,
            update_wc,
            )
        if revision_id is None or revision_id == self.last_revision():
            bp = self.get_branch_path()
            uuid = self.repository.uuid
            revnum = self.get_revnum()
        else:
            (uuid, bp, revnum), mapping = self.lookup_bzr_revision_id(
                revision_id)

        transport = get_transport(to_location)
        transport.ensure_base()
        to_path = transport.local_abspath(".")
        svn_url, readonly = bzr_to_svn_url(urlutils.join(self.repository.base, bp))
        wc.ensure_adm(to_path.encode("utf-8"), uuid,
                      svn_url, bzr_to_svn_url(self.repository.base)[0], revnum)
        with wc.Adm(None, to_path.encode("utf-8"), write_lock=True) as adm:
            conn = self.repository.svn_transport.connections.get(svn_url)
            try:
                update_wc(adm, to_path.encode("utf-8"), conn, svn_url, revnum)
            finally:
                if not conn.busy:
                    self.repository.svn_transport.add_connection(conn)

        dir = SvnCheckout(transport, SvnWorkingTreeDirFormat())
        return dir.open_workingtree()

    def _get_checkout_format(self, lightweight=False):
        from .workingtree import SvnWorkingTreeDirFormat
        if lightweight:
            return SvnWorkingTreeDirFormat()
        else:
            return format_registry.make_controldir('default')

    def create_checkout(self, to_location, revision_id=None, lightweight=False,
                        accelerator_tree=None, hardlink=False):
        """See Branch.create_checkout()."""
        if lightweight:
            return self._create_lightweight_checkout(to_location, revision_id)
        else:
            return self._create_heavyweight_checkout(to_location, revision_id,
                                                     hardlink=hardlink)

    def generate_revision_id(self, revnum):
        """Generate a new revision id for a revision on this branch."""
        assert isinstance(revnum, int)
        revmeta_history = self._revision_meta_history()
        take_next = False
        for revmeta, hidden, mapping in revmeta_history:
            if revmeta.metarev.revnum == revnum or take_next:
                if hidden:
                    take_next = True
                    continue
                return revmeta.get_revision_id(mapping)
            if revmeta.metarev.revnum < revnum:
                break
        if take_next:
            return NULL_REVISION
        raise NoSuchRevision(self, revnum)

    def get_config(self):
        return BranchConfig(self.user_url, self.repository.uuid)

    def get_config_stack(self):
        return SvnBranchStack(self.user_url, self.repository.uuid)

    def get_append_revisions_only(self):
        value = self.get_config_stack().get('append_revisions_only')
        if value is None:
            value = True
        return value

    def _get_nick(self, local=False, possible_master_transports=None):
        """Find the nick name for this branch.

        :return: Branch nick
        """
        ret = self.get_config().get_user_option("nick")
        if ret is not None:
            return ret
        bp = self._branch_path.strip("/")
        if isinstance(bp, str):
            bp = bp.decode('utf-8')
        if self._branch_path == "":
            return self.base.split("/")[-1]
        return bp

    def _set_nick(self, name):
        self.get_config().set_user_option("nick", name)

    nick = property(_get_nick, _set_nick)

    @deprecated_method(deprecated_in((2, 4, 0)))
    def set_revision_history(self, rev_history):
        """See Branch.set_revision_history()."""
        with self.lock_write():
            if rev_history == []:
                self._set_last_revision(NULL_REVISION)
            else:
                self._set_last_revision(rev_history[-1])
            self._revision_history_cache = rev_history

    def set_last_revision_info(self, revno, revid):
        """See Branch.set_last_revision_info()."""
        if type(revid) != str:
            raise InvalidRevisionId(revid, self)
        with self.lock_write():
            if self.last_revision() == revid:
                return
            self._set_last_revision(revid)

    def _set_last_revision(self, revid):
        if revid == NULL_REVISION:
            create_branch_with_hidden_commit(
                self.repository,
                self.get_branch_path(), NULL_REVISION,
                set_metadata=True, deletefirst=True)
        else:
            try:
                rev = self.repository.get_revision(revid)
            except NoSuchRevision:
                raise NotImplementedError("set_last_revision_info can't add ghosts")
            interrepo = InterToSvnRepository(self.repository, self.repository)
            try:
                base_revid = rev.parent_ids[0]
            except IndexError:
                base_foreign_info = None, None
            else:
                base_foreign_info = self.lookup_bzr_revision_id(rev.parent_ids[0])
            interrepo.push_single_revision(
                self.get_branch_path(), self.get_config_stack(), rev,
                push_metadata=True, root_action=("replace", self.get_revnum()),
                base_foreign_info=base_foreign_info)
        self._clear_cached_state()
        if self.is_locked():
            self._cached_last_revid = revid

    def last_revision_info(self):
        """See Branch.last_revision_info()."""
        last_revid = self.last_revision()
        return self.revision_id_to_revno(last_revid), last_revid

    def revision_id_to_revno(self, revision_id):
        """Given a revision id, return its revno"""
        if is_null(revision_id):
            return 0
        revmeta_history = self._revision_meta_history()
        # FIXME: Maybe we can parse revision_id as a bzr-svn roundtripped
        # revision?
        for revmeta, hidden, mapping in revmeta_history:
            if hidden:
                continue
            if revmeta.get_revision_id(mapping) == revision_id:
                return revmeta.get_revno(mapping)
        raise NoSuchRevision(self, revision_id)

    def get_root_id(self):
        tree = self.basis_tree()
        return tree.get_root_id()

    def set_push_location(self, location):
        """See Branch.set_push_location()."""
        trace.mutter("setting push location for %s to %s", self.base, location)
        self.get_config().set_user_option("push_location", location)

    def get_push_location(self):
        """See Branch.get_push_location()."""
        return self.get_config().get_user_option("push_location")

    def _iter_revision_meta_ancestry(self, pb=None):
        return self.repository._revmeta_provider._iter_reverse_revmeta_mapping_ancestry(
            self.get_branch_path(),
            self.repository.get_latest_revnum(), self.mapping,
            lhs_history=self._revision_meta_history(), pb=pb)

    def _revision_meta_history(self):
        if self._revmeta_cache is not None:
            return self._revmeta_cache
        revmeta_history = util.lazy_readonly_list(
                self.repository._revmeta_provider._iter_reverse_revmeta_mapping_history(
                    self.get_branch_path(),
                    self.repository.get_latest_revnum(),
                    to_revnum=0, mapping=self.mapping))
        if self.is_locked():
            self._revmeta_cache = revmeta_history
        return revmeta_history

    def get_rev_id(self, revno, history=None):
        """Find the revision id of the specified revno."""
        if revno == 0:
            return NULL_REVISION
        last_revno = self.revno()
        if revno <= 0 or revno > last_revno:
            raise NoSuchRevision(self, revno)
        count = last_revno - revno
        for (revmeta, hidden, mapping) in self._revision_meta_history():
            if hidden:
                continue
            if count == 0:
                assert revmeta.get_revno(mapping) == revno, "Expected %d, was (%r,%r) %d" % (revno, revmeta, mapping, revmeta.get_revno(mapping))
                return revmeta.get_revision_id(mapping)
            count -= 1
        raise AssertionError

    def _gen_revision_history(self):
        """Generate the revision history from last revision."""
        history = [revmeta.get_revision_id(mapping) for revmeta, hidden, mapping in self._revision_meta_history() if not hidden]
        history.reverse()
        return history

    def last_revision(self):
        """See Branch.last_revision()."""
        with self.lock_read():
            # Shortcut for finding the tip. This avoids expensive generation time
            # on large branches.
            if self._cached_last_revid is not None:
                return self._cached_last_revid
            last_revmeta, mapping = self.last_revmeta(skip_hidden=True)
            if last_revmeta is None:
                revid = NULL_REVISION
            else:
                revid = last_revmeta.get_revision_id(mapping)
            if self.is_locked():
                self._cached_last_revid = revid
            assert isinstance(revid, str), "not str: %r" % revid
            return revid

    def get_push_merged_revisions(self):
        return (self.layout.push_merged_revisions(self.project) and
                self.get_config_stack().get('push_merged_revisions'))

    def import_last_revision_info(self, source_repo, revno, revid, lossy=False):
        interrepo = InterToSvnRepository(source_repo, self.repository)
        base_revmeta, base_mapping = self.last_revmeta(skip_hidden=False)
        revidmap = interrepo.push_todo(self.last_revision(),
            base_revmeta.metarev.get_foreign_revid(),
            base_mapping, revid, self.layout,
            self.project, self.get_branch_path(), self.get_config_stack(),
            push_merged=self.get_push_merged_revisions(),
            overwrite=False, push_metadata=not lossy,
            append_revisions_only=True)
        return (revno, revidmap[revid][0])

    def import_last_revision_info_and_tags(self, source, revno, revid,
            lossy=False):
        (revno, revid) = self.import_last_revision_info(source.repository,
            revno, revid, lossy=lossy)
        self.tags.merge_to(source.tags, overwrite=False)
        return (revno, revid)

    def generate_revision_history(self, revision_id, last_rev=None,
        other_branch=None):
        """Create a new revision history that will finish with revision_id.

        :param revision_id: the new tip to use.
        :param last_rev: The previous last_revision. If not None, then this
            must be a ancestory of revision_id, or DivergedBranches is raised.
        :param other_branch: The other branch that DivergedBranches should
            raise with respect to.
        """
        with self.lock_write():
            # stop_revision must be a descendant of last_revision
            # make a new revision history from the graph
            graph = self.repository.get_graph()
            if last_rev is not None:
                if not graph.is_ancestor(last_rev, revision_id):
                    # our previous tip is not merged into stop_revision
                    raise DivergedBranches(self, other_branch)
            self._set_last_revision(revision_id)

    def _synchronize_history(self, destination, revision_id):
        """Synchronize last revision and revision history between branches.

        This version is most efficient when the destination is also a
        BzrBranch6, but works for BzrBranch5, as long as the destination's
        repository contains all the lefthand ancestors of the intended
        last_revision.  If not, set_last_revision_info will fail.

        :param destination: The branch to copy the history into
        :param revision_id: The revision-id to truncate history at.  May
          be None to copy complete history.
        """
        if revision_id is None:
            revision_id = self.last_revision()
        destination.generate_revision_history(revision_id)

    def is_locked(self):
        return self._lock_count != 0

    def break_lock(self):
        raise NotImplementedError(self.break_lock)

    def lock_write(self, token=None):
        """See Branch.lock_write()."""
        # TODO: Obtain lock on the remote server?
        if token is not None:
            raise TokenLockingNotSupported(self)
        if self._lock_mode:
            if self._lock_mode == 'r':
                raise ReadOnlyError(self)
            self._lock_count += 1
        else:
            self._lock_mode = 'w'
            self._lock_count = 1
        self.repository.lock_write()
        return BranchWriteLockResult(self.unlock, None)

    def lock_read(self):
        """See Branch.lock_read()."""
        if self._lock_mode:
            assert self._lock_mode in ('r', 'w')
            self._lock_count += 1
        else:
            self._lock_mode = 'r'
            self._lock_count = 1
        self.repository.lock_read()
        return LogicalLockResult(self.unlock)

    def unlock(self):
        """See Branch.unlock()."""
        self._lock_count -= 1
        if self._lock_count == 0:
            self._lock_mode = None
            self._clear_cached_state()
        self.repository.unlock()

    def _clear_cached_state(self):
        super(SvnBranch, self)._clear_cached_state()
        self._cached_last_revid = None
        self._revmeta_cache = None

    def get_parent(self):
        """See Branch.get_parent()."""
        return self.get_config().get_user_option("parent_location")

    def set_parent(self, url):
        """See Branch.set_parent()."""
        self.get_config().set_user_option("parent_location", url)

    def get_physical_lock_status(self):
        """See Branch.get_physical_lock_status()."""
        return False

    def get_stacked_on_url(self):
        raise UnstackableBranchFormat(self._format, self.base)

    def __str__(self):
        return '%s(%r)' % (self.__class__.__name__, self.base)

    __repr__ = __str__

    def _basic_push(self, target, overwrite=False, stop_revision=None):
        return InterBranch.get(self, target)._basic_push(
            overwrite, stop_revision)


class SvnBranchFormat(BranchFormat):
    """Branch format for Subversion Branches."""

    def network_name(self):
        return "subversion"

    def __get_matchingcontroldir(self):
        """See BranchFormat.__get_matchingcontroldir()."""
        from breezy.plugins.svn.remote import SvnRemoteFormat
        return SvnRemoteFormat()

    _matchingcontroldir = property(__get_matchingcontroldir)

    def get_format_description(self):
        """See BranchFormat.get_format_description."""
        return 'Subversion Smart Server'

    def get_foreign_tests_branch_factory(self):
        from .tests.test_branch import ForeignTestsBranchFactory
        return ForeignTestsBranchFactory()

    def initialize(self, to_controldir, name=None, repository=None,
                   append_revisions_only=None):
        """See BranchFormat.initialize()."""
        from .remote import SvnRemoteAccess
        if not isinstance(to_controldir, SvnRemoteAccess):
            raise IncompatibleFormat(self, to_controldir._format)
        return to_controldir.create_branch(
                name, append_revisions_only=append_revisions_only)

    def supports_tags(self):
        return True

    def make_tags(self, branch):
        if branch.supports_tags():
            return SubversionTags(branch)
        else:
            return tag.DisabledTags(branch)

    def supports_set_append_revisions_only(self):
        return True

    def supports_tags_referencing_ghosts(self):
        return False

    def tags_are_versioned(self):
        return True

    def supports_store_uncommitted(self):
        return False


class InterFromSvnBranch(GenericInterBranch):
    """InterBranch implementation that is optimized for copying from
    Subversion.

    The two main differences with the generic implementation are:
     * No revision numbers are calculated for the Subversion branch
       (since this requires browsing the entire history)
     * Only recent tags are fetched, since that saves a lot of
       history browsing operations
    """

    @staticmethod
    def _get_branch_formats_to_test():
        from breezy.branch import format_registry as branch_format_registry
        return [(SvnBranchFormat(), branch_format_registry.get_default())]

    def fetch(self, stop_revision=None, fetch_tags=None, find_ghosts=False,
              limit=None, exclude_non_mainline=None):
        """See InterBranch.fetch."""
        # we fetch here so that we don't process data twice in the
        # common case of having something to pull, and so that the
        # check for already merged can operate on the just fetched
        # graph, which will be cached in memory.
        (revmeta, mapping) = self.source.last_revmeta(skip_hidden=True)
        if stop_revision is None:
            todo = [self.source.last_revmeta(skip_hidden=True)]
        elif stop_revision == NULL_REVISION:
            todo = []
        else:
            todo = [self.source.repository._get_revmeta(stop_revision)]
        if limit is not None and len(todo) > limit:
            # No need to fetch tags if there are already up to 'limit'
            # revisions missing in mainline.
            fetch_tags = False
        if fetch_tags is None:
            c = self.source.get_config()
            fetch_tags = c.get_user_option_as_bool('branch.fetch_tags')
        if fetch_tags and self.source.supports_tags():
            tag_revmetas = self.source.tags._get_tag_dict_revmeta()
            d = resolve_tags_svn_ancestry(self.source, tag_revmetas)
            for name, (revmeta, mapping, revid) in d.iteritems():
                todo.append((revmeta, mapping))
        self._fetch_revmetas(todo, find_ghosts=find_ghosts, limit=limit,
                exclude_non_mainline=exclude_non_mainline)

    def _fetch_revmetas(self, revmetas, find_ghosts=False, limit=None,
            exclude_non_mainline=None):
        interrepo = InterFromSvnToInventoryRepository(self.source.repository,
            self.target.repository)
        revisionfinder = interrepo.get_revision_finder()
        for revmeta, mapping in revmetas:
            revisionfinder.find_until(revmeta.metarev.get_foreign_revid(),
                mapping, find_ghosts=find_ghosts,
                exclude_non_mainline=exclude_non_mainline)
        interrepo.fetch(needed=revisionfinder.get_missing(limit=limit),
            project=self.source.project, mapping=self.source.mapping)

    def _update_revisions(self, stop_revision=None, overwrite=False,
                         graph=None, fetch_tags=None,
                         fetch_non_mainline=None):
        "See InterBranch.update_revisions."""
        with self.source.lock_read():
            if stop_revision is None:
                stop_revision = self.source.last_revision()
                if is_null(stop_revision):
                    # if there are no commits, we're done.
                    return self.target.last_revision_info()

            # what's the current last revision, before we fetch [and
            # change it possibly]
            last_rev = self.target.last_revision()
            if fetch_non_mainline is None:
                fetch_non_mainline = True
            self.fetch(stop_revision=stop_revision, fetch_tags=fetch_tags,
                       exclude_non_mainline=(not fetch_non_mainline))
            # Check to see if one is an ancestor of the other
            if not overwrite:
                if graph is None:
                    graph = self.target.repository.get_graph()
                with self.target.lock_read():
                    if self.target._check_if_descendant_or_diverged(
                            stop_revision, last_rev, graph, self.source):
                        # stop_revision is a descendant of last_rev, but we
                        # aren't overwriting, so we're done.
                        return self.target.last_revision_info()
            self.target._clear_cached_state()
            self.target.generate_revision_history(stop_revision)
            return self.target.last_revision_info()

    def _basic_push(self, overwrite=False, stop_revision=None,
            fetch_non_mainline=False):
        result = BranchPushResult()
        result.source_branch = self.source
        result.target_branch = self.target
        graph = self.target.repository.get_graph(self.source.repository)
        result.old_revno, result.old_revid = self.target.last_revision_info()
        (result.new_revno, result.new_revid) = self._update_revisions(
            stop_revision, overwrite=overwrite, graph=graph,
            fetch_non_mainline=fetch_non_mainline)
        # FIXME: Tags
        return result

    def _update_tags(self, result, overwrite, tags_since_revnum):
        if not self.source.supports_tags():
            return
        tag_ret = self.source.tags.merge_to(
            self.target.tags, overwrite,
            _from_revnum=tags_since_revnum,
            _to_revnum=self.source.repository.get_latest_revnum())
        if isinstance(tag_ret, tuple):
            (result.tag_updates, result.tag_conflicts) = tag_ret
        else:
            result.tag_conflicts = tag_ret

    def _basic_pull(self, stop_revision, overwrite, run_hooks,
              _override_hook_target, _hook_master,
              fetch_non_mainline=None):
        self.target.lock_write()
        try:
            result = SubversionSourcePullResult()
            result.source_branch = self.source
            if _override_hook_target is None:
                result.target_branch = self.target
            else:
                result.target_branch = _override_hook_target

            (result.old_revno, result.old_revid) = \
                self.target.last_revision_info()
            if result.old_revid == NULL_REVISION:
                result.old_revmeta = None
                tags_since_revnum = None
            else:
                try:
                    result.old_revmeta, _ = \
                        self.source.repository._get_revmeta(result.old_revid)
                    tags_since_revnum = result.old_revmeta.metarev.revnum
                except NoSuchRevision:
                    result.old_revmeta = None
                    tags_since_revnum = None
            if stop_revision == NULL_REVISION:
                result.new_revid = NULL_REVISION
                result.new_revmeta = None
            elif stop_revision is not None:
                result.new_revmeta, _ = \
                    self.source.repository._get_revmeta(stop_revision)
            else:
                result.new_revmeta = None
            (result.new_revno, result.new_revid) = self._update_revisions(
                stop_revision, overwrite,
                fetch_non_mainline=fetch_non_mainline)
            self._update_tags(result, overwrite, tags_since_revnum)
            if _hook_master:
                result.master_branch = _hook_master
                result.local_branch = result.target_branch
            else:
                result.master_branch = result.target_branch
                result.local_branch = None
            if run_hooks:
                for hook in Branch.hooks['post_pull']:
                    hook(result)
        finally:
            self.target.unlock()
        return result

    def pull(self, overwrite=False, stop_revision=None,
             run_hooks=True, possible_transports=None,
             _override_hook_target=None, local=False,
             fetch_non_mainline=None):
        """See InterBranch.pull()."""
        bound_location = self.target.get_bound_location()
        if local and not bound_location:
            raise LocalRequiresBoundBranch()
        master_branch = None
        source_is_master = False
        self.source.lock_read()
        if bound_location:
            # bound_location comes from a config file, some care has to be
            # taken to relate it to source.user_url
            normalized = urlutils.normalize_url(bound_location)
            try:
                relpath = self.source.user_transport.relpath(normalized)
                source_is_master = (relpath == '')
            except (PathNotChild, urlutils.InvalidURL):
                source_is_master = False
        if not local and bound_location and not source_is_master:
            # not pulling from master, so we need to update master.
            master_branch = self.target.get_master_branch(possible_transports)
            master_branch.lock_write()
        try:
            try:
                if master_branch:
                    # pull from source into master.
                    master_branch.pull(self.source, overwrite, stop_revision,
                        run_hooks=False, fetch_non_mainline=fetch_non_mainline)
                result = self._basic_pull(stop_revision, overwrite, run_hooks,
                    _override_hook_target, _hook_master=master_branch,
                    fetch_non_mainline=fetch_non_mainline)
            finally:
                self.source.unlock()
        finally:
            if master_branch:
                master_branch.unlock()
        return result

    @classmethod
    def is_compatible(self, source, target):
        if not isinstance(source, SvnBranch):
            return False
        if isinstance(target, SvnBranch):
            return False
        return True

InterBranch.register_optimiser(InterFromSvnBranch)


class InterToSvnBranch(InterBranch):
    """InterBranch implementation that is optimized for copying to
    Subversion.

    """

    @staticmethod
    def _get_branch_formats_to_test():
        from breezy.branch import format_registry as branch_format_registry
        return [
            (branch_format_registry.get_default(), SvnBranchFormat()),
            (SvnBranchFormat(), SvnBranchFormat())]

    def _target_is_empty(self, graph, revid):
        parent_revids = tuple(graph.get_parent_map([revid])[revid])
        if parent_revids != (NULL_REVISION,):
            return False
        tree_contents = self.target.repository.svn_transport.get_dir(
            self.target.get_branch_path(), self.target.get_revnum())[0]
        return tree_contents == {}

    def copy_content_into(self, revision_id=None):
        if revision_id is None:
            revision_id = self.source.last_revision()
        with self.source.lock_read():
            with self.target.lock_write():
                self._push(revision_id, overwrite=True, push_metadata=True)
            try:
                parent = self.source.get_parent()
            except InaccessibleParent as e:
                trace.mutter('parent was not accessible to copy: %s', e)
            else:
                if parent:
                    self.target.set_parent(parent)

    def _push(self, stop_revision, overwrite, push_metadata):
        old_last_revid = self.target.last_revision()
        if old_last_revid == stop_revision:
            return (old_last_revid, { old_last_revid: (old_last_revid, None) })
        push_merged = self.target.get_push_merged_revisions()
        interrepo = InterToSvnRepository(
            self.source.repository, self.target.repository)
        base_revmeta, base_mapping = self.target.last_revmeta(skip_hidden=False)
        try:
            revidmap = interrepo.push_branch(self.target.get_branch_path(),
                    self.target.get_config_stack(), old_last_revid,
                    base_revmeta.metarev.get_foreign_revid(),
                    base_mapping,
                    stop_revision=stop_revision, overwrite=overwrite,
                    push_metadata=push_metadata, push_merged=push_merged,
                    layout=self.target.layout, project=self.target.project)
        except SubversionBranchDiverged as e:
            if self._target_is_empty(interrepo.get_graph(), e.target_revid):
                raise PushToEmptyBranch(self.target, self.source)
            raise DivergedBranches(self.target, self.source)
        return (old_last_revid, revidmap)

    def _update_revisions(self, stop_revision=None, overwrite=False,
            lossy=False, fetch_non_mainline=False):
        """Push derivatives of the revisions missing from target from source
        into target.

        :param target: Branch to push into
        :param source: Branch to retrieve revisions from
        :param stop_revision: If not None, stop at this revision.
        :return: Map of old revids to new revids.
        """
        if stop_revision is None:
            stop_revision = ensure_null(self.source.last_revision())
        (old_last_revid, revid_map) = self._push(
            stop_revision, overwrite=overwrite, push_metadata=(not lossy))
        self.target._clear_cached_state()
        new_last_revid = self.target.last_revision()
        return (old_last_revid,
                new_last_revid,
                dict([(k, v[0]) for (k, v) in revid_map.iteritems()]))

    def fetch(self, stop_revision=None, fetch_tags=None, find_ghosts=False,
            limit=None, exclude_non_mainline=None):
        """Fetch into a subversion repository."""
        # FIXME: Handle fetch_tags
        # FIXME: Handle find_ghosts
        interrepo = InterToSvnRepository(
            self.source.repository, self.target.repository)
        if stop_revision is None:
            stop_revision = self.source.last_revision()
        interrepo.fetch(revision_id=stop_revision, limit=limit,
            exclude_non_mainline=exclude_non_mainline)

    def update_tags(self, result, overwrite=False):
        ret = self.source.tags.merge_to(self.target.tags, overwrite)
        if isinstance(ret, tuple):
            (result.tag_updates, result.tag_conflicts) = ret
        else:
            result.tag_conflicts = ret

    def _basic_push(self, overwrite=False, stop_revision=None, lossy=False,
            fetch_non_mainline=False):
        """Basic implementation of push without bound branches or hooks.

        Must be called with source read locked and target write locked.
        """
        if lossy and isinstance(self.source, SvnBranch):
            raise LossyPushToSameVCS(self.source, self.target)
        return self._update_revisions(stop_revision, overwrite=overwrite,
            lossy=lossy, fetch_non_mainline=fetch_non_mainline)

    def push(self, overwrite=False, stop_revision=None,
            lossy=False, _override_hook_source_branch=None,
            fetch_non_mainline=None):
        """See InterBranch.push()."""
        result = SubversionTargetBranchPushResult()
        result.target_branch = self.target
        result.master_branch = self.target
        result.local_branch = None
        result.source_branch = self.source
        with self.source.lock_read(), self.target.lock_write():
            (result.old_revid, result.new_revid, result.revidmap) = (
                    self._basic_push(
                        stop_revision=stop_revision, overwrite=overwrite,
                        lossy=lossy, fetch_non_mainline=fetch_non_mainline))
            self.update_tags(result, overwrite)
            for hook in Branch.hooks['post_push']:
                hook(result)
            return result

    def pull(self, overwrite=False, stop_revision=None,
             run_hooks=True, possible_transports=None,
             local=False, fetch_non_mainline=False):
        """See InterBranch.pull()."""
        if local:
            raise LocalRequiresBoundBranch()
        result = SubversionTargetPullResult()
        result.source_branch = self.source
        result.local_branch = None
        result.target_branch = self.target
        result.master_branch = self.target
        with self.source.lock_read(), self.target.lock_write():
            (result.old_revid, result.new_revid, result.revidmap) = \
                self._update_revisions(stop_revision, overwrite,
                        fetch_non_mainline=fetch_non_mainline)
            self.update_tags(result, overwrite)
            if run_hooks:
                for hook in Branch.hooks['post_pull']:
                    hook(result)
            return result

    @classmethod
    def is_compatible(self, source, target):
        if not isinstance(target, SvnBranch):
            return False
        return True


InterBranch.register_optimiser(InterToSvnBranch)
