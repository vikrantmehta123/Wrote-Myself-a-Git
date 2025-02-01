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
        case "add"          : cmd_add(args)
        case "cat-file"     : cmd_cat_file(args)
        case "check-ignore" : cmd_check_ignore(args)
        case "checkout"     : cmd_checkout(args)
        case "commit"       : cmd_commit(args)
        case "hash-object"  : cmd_hash_object(args)
        case "init"         : cmd_init(args)
        case "log"          : cmd_log(args)
        case "ls-files"     : cmd_ls_files(args)
        case "ls-tree"      : cmd_ls_tree(args)
        case "rev-parse"    : cmd_rev_parse(args)
        case "rm"           : cmd_rm(args)
        case "show-ref"     : cmd_show_ref(args)
        case "status"       : cmd_status(args)
        case "tag"          : cmd_tag(args)
        case _              : print("Bad command.")

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

class GitObject (object):

    def __init__(self, data=None):
        if data != None:
            self.deserialize(data)
        else:
            self.init()

    def serialize(self, repo):
        """This function MUST be implemented by subclasses.

It must read the object's contents from self.data, a byte string, and
do whatever it takes to convert it into a meaningful representation.
What exactly that means depend on each subclass.

        """
        raise Exception("Unimplemented!")

    def deserialize(self, data):
        raise Exception("Unimplemented!")

    def init(self):
        pass # Just do nothing. This is a reasonable default!

def object_read(repo, sha):
    """Read object sha from Git repository repo.  Return a
    GitObject whose exact type depends on the object."""

    path = repo_file(repo, "objects", sha[0:2], sha[2:])

    if not os.path.isfile(path):
        return None

    with open (path, "rb") as f:
        raw = zlib.decompress(f.read())

        # Read object type
        x = raw.find(b' ')
        fmt = raw[0:x]

        # Read and validate object size
        y = raw.find(b'\x00', x)
        size = int(raw[x:y].decode("ascii"))
        if size != len(raw)-y-1:
            raise Exception(f"Malformed object {sha}: bad length")

        # Pick constructor
        match fmt:
            case b'commit' : c=GitCommit
            case b'tree'   : c=GitTree
            case b'tag'    : c=GitTag
            case b'blob'   : c=GitBlob
            case _:
                raise Exception(f"Unknown type {fmt.decode("ascii")} for object {sha}")

        # Call constructor and return object
        return c(raw[y+1:])

def object_write(obj, repo=None):
    # Serialize object data
    data = obj.serialize()
    # Add header
    result = obj.fmt + b' ' + str(len(data)).encode() + b'\x00' + data
    # Compute hash
    sha = hashlib.sha1(result).hexdigest()

    if repo:
        # Compute path
        path=repo_file(repo, "objects", sha[0:2], sha[2:], mkdir=True)

        if not os.path.exists(path):
            with open(path, 'wb') as f:
                # Compress and write
                f.write(zlib.compress(result))
    return sha

class GitBlob(GitObject):
    fmt=b'blob'

    def serialize(self):
        return self.blobdata

    def deserialize(self, data):
        self.blobdata = data

argsp = argsubparsers.add_parser("cat-file",
                                 help="Provide content of repository objects")

argsp.add_argument("type",
                   metavar="type",
                   choices=["blob", "commit", "tag", "tree"],
                   help="Specify the type")

argsp.add_argument("object",
                   metavar="object",
                   help="The object to display")


def cmd_cat_file(args):
    repo = repo_find()
    cat_file(repo, args.object, fmt=args.type.encode())

def cat_file(repo, obj, fmt=None):
    obj = object_read(repo, object_find(repo, obj, fmt=fmt))
    sys.stdout.buffer.write(obj.serialize())

def object_find(repo, name, fmt=None, follow=True):
    return name

argsp = argsubparsers.add_parser(
    "hash-object",
    help="Compute object ID and optionally creates a blob from a file")

argsp.add_argument("-t",
                   metavar="type",
                   dest="type",
                   choices=["blob", "commit", "tag", "tree"],
                   default="blob",
                   help="Specify the type")

argsp.add_argument("-w",
                   dest="write",
                   action="store_true",
                   help="Actually write the object into the database")

argsp.add_argument("path",
                   help="Read object from <file>")


def cmd_hash_object(args):
    if args.write:
        repo = repo_find()
    else:
        repo = None

    with open(args.path, "rb") as fd:
        sha = object_hash(fd, args.type.encode(), repo)
        print(sha)

def object_hash(fd, fmt, repo=None):
    """ Hash object, writing it to repo if provided."""
    data = fd.read()

    # Choose constructor according to fmt argument
    match fmt:
        case b'commit' : obj=GitCommit(data)
        case b'tree'   : obj=GitTree(data)
        case b'tag'    : obj=GitTag(data)
        case b'blob'   : obj=GitBlob(data)
        case _: raise Exception(f"Unknown type {fmt}!")

    return object_write(obj, repo)