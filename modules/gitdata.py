from sh import git
import sh
import re
import os, sys
import locket
import functools
from locket import LockError
import codecs
from peyotl.phylesystem import get_HEAD_SHA1
import api_utils
_LOG = api_utils.get_logger(__name__)
class MergeException(Exception):
    pass

class GitData(object):
    def __init__(self, repo):
        """Create a GitData object to interact with a Git repository

        Example:
        gd   = GitData(repo="/home/user/git/foo")

        Note that this requires write access to the
        git repository directory, so it can create a
        lockfile in the .git directory.

        """
        self.repo = repo
        self.git_dir = os.path.join(repo, '.git')
        self.lock_file     = os.path.join(self.git_dir, "API_WRITE_LOCK")
        self.lock_timeout  = 30
        self.lock          = locket.lock_file(self.lock_file, timeout=self.lock_timeout)
        
        if os.path.isdir("{}/.git".format(self.repo)):
           self.gitdir="--git-dir={}/.git".format(self.repo)
           self.gitwd="--work-tree={}".format(self.repo)
        else: #EJM needs a test?
            print("Not a Git repo") 
           #EJM not sure where this will go in web2py
            

    def acquire_lock(self):
        "Acquire a lock on the git repository"
        _LOG.debug('Acquiring lock')
        self.lock.acquire()

    def release_lock(self):
        "Release a lock on the git repository"
        _LOG.debug('Releasing lock')
        self.lock.release()

    def current_branch(self):
        "Return the current branch name"
        branch_name = git(self.gitdir, self.gitwd, "symbolic-ref", "HEAD")
        return branch_name.replace('refs/heads/','').strip()

    def checkout_master(self):
        git(self.gitdir, self.gitwd, "checkout", "master")

    def newest_study_id(self):
        "Return the numeric part of the newest study_id"
        #git(self.gitdir, "stash") #EJM not clear why, ask Mark
        git(self.gitdir, self.gitwd, "checkout","master")
        dirs = []
        # first we look for studies already in our master branch
        for f in os.listdir("study/"):
            if os.path.isdir("study/%s" % f):
                # ignore alphabetic prefix, o = created by opentree API
                if f[0].isalpha():
                    dirs.append(int(f[1:]))
                else:
                    dirs.append(int(f))

        # next we must look at local branch names for new studies
        # without --no-color we get terminal color codes in the branch output
        branches = git(self.gitdir, self.gitwd,"branch","--no-color")
        branches = [ b.strip() for b in branches ]
        for b in branches:
            mo = re.match(".+_o(\d+)",b)
            if mo:
                dirs.append(int(mo.group(1)))

        dirs.sort()
        return dirs[-1]

    def fetch_study(self, study_id):
        """Return the contents of the given study_id, and the SHA1 of the HEAD.

        If the study_id does not exist, it returns the empty string.
        """
        study_filename = "%s/study/%s/%s.json" % (self.repo, study_id, study_id)
        head_sha = get_HEAD_SHA1(self.git_dir)
        try:
            f = codecs.open(study_filename, mode='rU', encoding='utf-8')
        except:
            return '', head_sha
        return f.read(), head_sha

    def branch_exists(self, branch):
        """Returns true or false depending on if a branch exists"""
        try:
            git(self.gitdir, self.gitwd, "rev-parse",branch)
        except sh.ErrorReturnCode:
            return False
        return True

    def create_or_checkout_branch(self,branch):
        if self.branch_exists(branch):
            git(self.gitdir, self.gitwd, "checkout",branch)
            
        else:
            # Create this new branch off of master, NOT the currently-checked out branch!
            #EJM wait why?
            git(self.gitdir, self.gitwd, "checkout","master")
            git(self.gitdir, self.gitwd, "checkout","-b",branch)
    
    def remove_study(self,study_id, branch, author="OpenTree API <api@opentreeoflife.org>"):
        """Remove a study

        Given a study_id, branch and optionally an
        author, remove a study on the given branch
        and attribute the commit to author.

        Returns the SHA of the commit on branch.

        """
        study_dir      = "{}/study/{}".format(self.repo,study_id) #TODO change directory
        study_filename = "{}/{}.json".format(study_dir, study_id)

        self.create_or_checkout_branch(branch)
        if not os.path.isdir(study_dir):
                # branch already exists locally with study removed
                # so just return the commit SHA
                return git(self.gitdir, self.gitwd, "rev-parse","HEAD").strip()

        git(self.gitdir, self.gitwd,"rm","-rf", study_dir)

        git(self.gitdir, self.gitwd, "commit",author=author, message="Delete Study #%s via OpenTree API" % study_id)

        new_sha = git(self.gitdir, self.gitwd, "rev-parse","HEAD")

        return new_sha.strip()

    def write_study(self,study_id, content, branch, author="OpenTree API <api@opentreeoflife.org>"):
        """Write a study

        Given a study_id, content, branch and
        optionally an author, write a study on the
        given branch and attribute the commit to
        author. If the branch does not yet exist,
        it will be created. If the study is being
        created, it's containing directory will be
        created as well.

        Returns the SHA of the new commit on branch.

        """
        study_dir      = "{}/study/{}".format(self.repo,study_id) #TODO EJM change directory
        study_filename = "{}/{}.json".format(study_dir, study_id) 
        # If there are uncommitted changes to our repo, stash them so this commit can proceed
        #git(self.gitdir, self.gitwd, "stash") #EJM not clear why

        self.create_or_checkout_branch(branch)
        
        # create a study directory if this is a new study EJM- what if it isn't?
        if not os.path.isdir(study_dir):
            os.mkdir(study_dir)

        file = open(study_filename, 'w')
        file.write(content)
        file.close()

        git(self.gitdir, self.gitwd, "add",study_filename)

        git(self.gitdir, self.gitwd,  "commit",author=author, message="Update Study #%s via OpenTree API" % study_id)

        new_sha = git(self.gitdir, self.gitwd,  "rev-parse","HEAD")

        return new_sha.strip()

    def merge(self, branch, base_branch="master"):
        """
        Merge the the given WIP branch to master (or base_branch, if specified)

        If the merge fails, the merge will be aborted
        and then a MergeException will be thrown. The
        message of the MergeException will be the
        "git status" output, so details about merge
        conflicts can be determined.

        """

        current_branch = self.current_branch()
        if current_branch != base_branch:
            git(self.gitdir, self.gitwd, "checkout",base_branch)

        # Always create a merge commit, even if we could fast forward, so we know
        # when merges occured
        try:
            merge_output = git(self.gitdir, self.gitwd, "--no-ff","merge", branch)
        except sh.ErrorReturnCode:
            # attempt to reset things so other operations can
            # continue
            output = git(self.gitdir, self.gitwd, "status")
            git(self.gitdir, self.gitwd, "merge""--abort")

            # re-raise the exception so other code can decide
            # what to do with it
            raise MergeException(output)

        # the merge succeeded, so remove the local WIP branch
        git(self.gitdir, self.gitwd, "branch","-d", branch)

        new_sha      = git(self.gitdir, self.gitwd, "rev-parse","HEAD")
        return new_sha.strip()

    def delete_remote_branch(self, remote, branch, env={}):
        "Delete a remote branch"
        # deleting a branch is the same as
        # git push remote :branch
        self.push(remote, env, ":%s" % branch)

    def push(self, remote, env={}, branch=None):
        """
        Push a branch to a given remote

        Given a remote, env and branch, push branch
        to remote and add the environment variables
        in the env dict to the environment of the
        "git push" command.

        If no branch is given, the current branch
        will be used.

        The ability to specify env is so that PKEY
        and GIT_SSH can be specified so Git can use
        different SSH credentials than the current
        user (i.e. deploy keys for Github). If PKEY
        is not defined, the environment will not be
        over-ridden.

        """
        if branch:
            branch_to_push = branch
        else:
            branch_to_push = self.current_branch()

        # if there is no PKEY, we don't need to override env
        # We are explicit about what we are pushing, since the default behavior
        # is different in different versions of Git and/or by configuration
        if env["PKEY"]:
            new_env = os.environ.copy()
            new_env.update(env)
            git(self.gitdir, self.gitwd, "push",remote, branch_to_push, _env=new_env)
        else:
            git(self.gitdir, self.gitwd, "push",remote, branch_to_push)

    def pull(self, remote, env={}, branch=None):
        """
        Pull a branch from a given remote

        Given a remote, env and branch, pull branch
        from remote and add the environment variables
        in the env dict to the environment of the
        "git pull" command.

        If no branch is given, the current branch
        will be updated.
        """
        if branch:
            branch_to_pull = branch
        else:
            branch_to_pull = self.current_branch()

        # if there is no PKEY, we don't need to override env
        # We are explicit about what we are pushing, since the default behavior
        # is different in different versions of Git and/or by configuration
        if env["PKEY"]:
            new_env = os.environ.copy()
            new_env.update(env)
            git(self.gitdir, self.gitwd, "pull",remote, branch_to_pull, _env=new_env)
        else:
            git(self.gitdir, self.gitwd, "pull",remote, branch_to_pull)

        new_sha      = git(self.gitdir, self.gitwd, "rev-parse","HEAD")
        return new_sha.strip()
