Zenodo integration
==================

TheoCP2K is archived with Zenodo through the GitHub-Zenodo integration.

DOI
---

The archived ``v0.1.4`` release has the version-specific DOI:

``10.5281/zenodo.22772887``

https://doi.org/10.5281/zenodo.22772887

The concept DOI representing all archived versions of TheoCP2K is:

``10.5281/zenodo.22772886``

https://doi.org/10.5281/zenodo.22772886

The latest archived DOI for this GitHub repository can also be resolved through
the Zenodo repository badge endpoint:

https://zenodo.org/badge/latestdoi/1362776359

Repository metadata
-------------------

The repository contains:

* ``CITATION.cff`` for GitHub's **Cite this repository** feature and generic
  citation metadata. For version ``0.1.4`` it contains the version-specific
  Zenodo DOI.
* ``.zenodo.json`` for Zenodo-specific release metadata.

When both files are present, Zenodo uses ``.zenodo.json`` when archiving a
GitHub release, while GitHub can still use ``CITATION.cff`` for its citation
interface.

Archiving releases
------------------

The GitHub-Zenodo integration is enabled for ``mattiamerlo-bot/TheoCP2K``.
The first archived release is ``v0.1.4``. New GitHub releases are ingested by
Zenodo and receive a version-specific DOI; the concept DOI remains the stable
identifier for the software across versions.
