"""FRONTEND_ORIGIN is a list; NEXT_PUBLIC_APP_URL is not.

One deployment answers on two hostnames — the legacy ``*-HASH-REGION.a.run.app``
name and the newer ``*-PROJECTNUMBER.REGION.run.app`` one — and the browser sends
whichever the user typed. CORS therefore has to allow both, so FRONTEND_ORIGIN
became comma-separated.

NEXT_PUBLIC_APP_URL is fed from the same variable and is a single URL the app
concatenates paths onto. Passing the list straight through would bake
``https://a,https://b`` into the bundle and produce
``https://a,https://b/settings?...`` at runtime — a broken link introduced by the
CORS fix, in a redirect path nothing routinely exercises.

Both build paths take the first entry as canonical. These tests pin that,
because the two files are edited independently and only one of them failing is
worse than both failing.
"""

from __future__ import annotations

import pathlib
import re

import pytest


ROOT = pathlib.Path(__file__).resolve().parents[2]
DEPLOY_SH = ROOT / "ops" / "deploy.sh"
CLOUDBUILD = ROOT / "cloudbuild.yaml"


@pytest.mark.skipif(not DEPLOY_SH.exists(), reason="ops/deploy.sh not in this checkout")
class TestDeployScript:
    def test_app_url_takes_only_the_first_origin(self):
        src = DEPLOY_SH.read_text(encoding="utf-8")
        assert "${FRONTEND_ORIGIN%%,*}" in src

    def test_the_whole_list_is_not_passed_as_the_app_url(self):
        """The regression: the build arg fed straight from the allow-list."""
        src = DEPLOY_SH.read_text(encoding="utf-8")
        assert 'NEXT_PUBLIC_APP_URL="${FRONTEND_ORIGIN:-}"' not in src

    def test_cors_still_receives_every_origin(self):
        """Trimming the app URL must not trim the allow-list it came from."""
        src = DEPLOY_SH.read_text(encoding="utf-8")
        assert "FRONTEND_ORIGIN=${FRONTEND_ORIGIN:-}" in src


@pytest.mark.skipif(not CLOUDBUILD.exists(), reason="cloudbuild.yaml not in this checkout")
class TestCloudBuild:
    def test_app_url_takes_only_the_first_origin(self):
        src = CLOUDBUILD.read_text(encoding="utf-8")
        assert "%%,*}" in src, "cloudbuild should trim the origin list for NEXT_PUBLIC_APP_URL"

    def test_the_whole_list_is_not_passed_as_the_app_url(self):
        src = CLOUDBUILD.read_text(encoding="utf-8")
        assert 'NEXT_PUBLIC_APP_URL="${_FRONTEND_ORIGIN}"' not in src

    def test_the_substitution_is_landed_in_a_shell_variable_first(self):
        """``${_FRONTEND_ORIGIN}`` is a Cloud Build substitution, not a shell
        variable, so bash's %% operator cannot be applied to it directly."""
        src = CLOUDBUILD.read_text(encoding="utf-8")
        assert re.search(r'ORIGINS="\$\{_FRONTEND_ORIGIN\}"', src)
        assert re.search(r'APP_URL="\$\$\{ORIGINS%%,\*\}"', src)
