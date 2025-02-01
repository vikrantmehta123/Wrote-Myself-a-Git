import argparse
import configparser
from datetime import datetime
import grp, pwd
from fnmatch import fnmatch
import hashlib
from math import ceil
import os
import re
import sys
import zlib


argparser = argparse.ArgumentParser(description='The stupidest content tracker')
argsubparsers = argparser.add_subparsers(title='Commands', dest='command')
argsubparsers.required = True

def main(argv=sys.argv[1:]):
    args = argparser.parse_args(argv)
    match args.command:
        case 'cat-file'    : cmd_cat_file(args)
        case 'init'        : cmd_init(args)
        case 'hash-object' : cmd_hash_object(args)

class GitRepository(object):
    """A Git Repository"""

    worktree = None
    gitdir = None
    conf = None

    def __init__(self, path, force=False):
        self.worktree = path
        self.gitdir = os.path.join(path, '.git')

        # Check if the repository is a git repository ( except when force is True )
        if not (force or os.path.isdir(self.gitdir)):
            raise Exception(f"Not a git repository {path}")

        # Git has a configuration file in .git. Read those configs        
        self.conf = configparser.ConfigParser()
        cf = repo_file(self, 'config')

        if cf and os.path.exists(cf):
            self.conf.read([cf])
        
        # If force, then continues. Else, raise an exception if config is not there
        elif not force:
            raise Exception("Config file is missing")
        
        if not force:
            vers = int(self.conf.get('core', 'repositoryformatversion'))

            # Git requires the repository format version to be zero
            if vers !=0:
                raise Exception(f"Unsupported repositoryformatversion: {vers}")
            

# Some path manipulation utility functions
def repo_path(repo:GitRepository, *path) -> str:
    """
    *path -> makes the function variadic, so it can be called with multiple path
            components as separate arguments. For example, 
            repo_path(repo, "objects", "df", "<some hash>") is a valid call. 
            The function receives path as a list 
    """
    return os.path.join(repo.gitdir, *path)

def repo_file(repo:GitRepository, *path, mkdir=False):
    """
    Same as repo_path, but create dirname(*path) if absent.  For example, 
    repo_file(r, \"refs\", \"remotes\", \"origin\", \"HEAD\") will create
    .git/refs/remotes/origin.
    That is, this treats the last entry in the path as file, and creates 
    intermediate dirs if required.
    """

    if repo_dir(repo, *path[:-1], mkdir=mkdir):
        return repo_path(repo, *path)

def repo_dir(repo:GitRepository, *path, mkdir=False):
    """
    Same as repo_path, but mkdir *path if absent if mkdir. Treats the entire path
    as a directory. Creates intermediate directories if required.
    """

    path = repo_path(repo, *path)

    if os.path.exists(path):
        if (os.path.isdir(path)):
            return path
        else:
            raise Exception(f"Not a directory {path}")

    if mkdir:
        os.makedirs(path)
        return path
    else:
        return None
    
def repo_create(path):
    """Creates a Git repository at the given path"""

    # The first time you create a repo. You create using force.
    repo = GitRepository(path=path, force=True)

    # The path either should not exist or be an empty git directory
    if os.path.exists(repo.worktree):

        if not os.path.isdir(repo.worktree):  # repo.worktree = path in args
            raise Exception(f"{path} is not a directory")
        # The .git directory needs to be empty
        if os.path.exists(repo.gitdir) and os.listdir(repo.gitdir):
            raise Exception(f"{path} us not empty")
        
    else:
        os.makedirs(repo.worktree)
        
    # When you initialize a git repo, you create some additional folders / files.
    # These dirs are created here.
    assert repo_dir(repo, 'branches', mkdir=True)
    assert repo_dir(repo, 'objects', mkdir=True)
    assert repo_dir(repo, 'refs', 'tags', mkdir=True)
    assert repo_dir(repo, 'refs', 'heads', mkdir=True)

    # The repos description, head, and config files
    with open(repo_file(repo, 'description'), 'w') as f:
        f.write("Unnamed repository; edit this file-'description'- to name the repo.")

    with open(repo_file(repo, 'HEAD'), 'w') as f:
        f.write("ref: refs/heads/master\n")

    with open(repo_file(repo, 'config'), 'w') as f:
        config = repo_default_config()
        config.write(f)

    return repo

def repo_default_config():
    """
    Git config is a simple .ini file, with a [core] tag which has three (or 4) 
    fields. Here, we're supporting the bare minimum configs. Git supports 
    some additional config also.
    """
    ret = configparser.ConfigParser()

    ret.add_section("core")
    ret.set("core", "repositoryformatversion", "0")
    ret.set("core", "filemode", "false")
    ret.set("core", "bare", "false")

    return ret

# The init command: wyag init [path]. Works like: git init [path]

argsp = argsubparsers.add_parser('init', help='Initialize a new, empty repository')
argsp.add_argument('path', metavar='directory', nargs='?', default='.', 
                   help='Where to create the repository.')

# The bridge function that calls the repo create function when the init command 
# is called
def cmd_init(args):
    repo_create(args.path)


def repo_find(path='.', required=True):
    """
    A helper function to find the .git directory of the current repository
    For example, the repo may be at "/home/myproject"
    but you may be working in "/home/myproject/src/api/some_api.py"

    So from the file path, we need to find the root directory for the repo.
    """
    path = os.path.realpath('.')

    if os.path.isdir(os.path.join(path, ".git")):
        return GitRepository(path)


    # If we haven't returned, recurse in parent
    parent = os.path.realpath(os.path.join(path, ".."))

    if parent == path:
        # Raise the exception when no repo was find ( after recursing till '/')
        if required:
            raise Exception("No git directory.")
        else:
            return None

    # Recursive case
    return repo_find(parent, required)


# git hash-object: converts an existing file into a git 'object'
# git cat-file: prints an existing git object to standard output

