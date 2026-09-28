"""vit — git-style version control for video timelines.

Layers (each depends only on the ones above it):

    vit.git          GitRepository: every git command, via the system binary
    vit.timeline     models + domain-split JSON files on disk
    vit.project      VitProject: a git repo of timeline JSON
    vit.diff         human-readable timeline diffs
    vit.validation   timeline consistency checks
    vit.merge        clip-level three-way merge + merge orchestration
"""

__version__ = "0.1.0"
