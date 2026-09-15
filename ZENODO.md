Zenodo integration
==================

TheoCP2K is prepared for archival with Zenodo through the GitHub-Zenodo
integration.

Repository metadata
-------------------

The repository contains:

* ``CITATION.cff`` for GitHub's **Cite this repository** feature and generic
  citation metadata.
* ``.zenodo.json`` for Zenodo-specific release metadata.

When both files are present, Zenodo uses ``.zenodo.json`` when archiving a
GitHub release, while GitHub can still use ``CITATION.cff`` for its citation
interface.

One-time Zenodo setup
---------------------

1. Sign in to https://zenodo.org/ and link the GitHub account that owns this
   repository.
2. Open the Zenodo GitHub integration page from the profile menu.
3. Use **Sync now** if needed, find ``mattiamerlo-bot/TheoCP2K``, and enable
   the repository with the integration toggle.
4. Once enabled, Zenodo installs the repository webhook needed to detect new
   GitHub releases.

Archiving releases
------------------

After the integration is enabled, create a new GitHub release in the normal
TheoCP2K release workflow. Zenodo will ingest the release and create an
archived software record with a version-specific DOI. Zenodo also maintains a
concept DOI representing all versions of the software.

The existing ``v0.1.3`` release predates this repository-side Zenodo setup.
If it is not automatically available for archival after enabling the
integration, create the next TheoCP2K release normally; that release will be
processed through the enabled integration.

After the first Zenodo record exists
------------------------------------

Add the Zenodo DOI badge and DOI citation to ``README.rst`` and, if desired,
add the DOI to ``CITATION.cff``. The DOI must not be guessed or pre-filled:
it should be copied from the Zenodo record after publication.
