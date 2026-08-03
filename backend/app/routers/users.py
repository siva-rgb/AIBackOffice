from __future__ import annotations

from datetime import datetime, timezone

from pydantic import Field

from fastapi import APIRouter, Depends, HTTPException, Request

from .. import store
from ..backends.user_data import CURRENT_CONSENT_VERSION
from ..dependencies import get_current_user
from ..models import BusinessProfile, CamelModel, User

router = APIRouter(prefix="/api", tags=["users"])


class ProfileUpdate(CamelModel):
    """Partial profile update used by the onboarding wizard and settings.

    All fields optional — only the keys provided are written. business_type has
    no column in the schema yet, so it is accepted but not persisted.
    """

    full_name: str | None = None
    business_name: str | None = None
    country: str | None = None
    currency: str | None = None
    onboarding_completed: bool | None = None
    business_type: str | None = Field(default=None, exclude=True)


@router.get("/me", response_model=User)
async def me(user: User = Depends(get_current_user)):
    return user


@router.patch("/me", response_model=User)
async def update_me(patch: ProfileUpdate, user: User = Depends(get_current_user)):
    # Only persist columns that exist on public.users; drop unset keys so we
    # never overwrite a field with null.
    data = patch.model_dump(exclude_none=True, exclude={"business_type"})
    if not data:
        return user
    updated = store.update_user(user.id, data)
    if not updated:
        raise HTTPException(status_code=404, detail="User not found")
    if patch.onboarding_completed and not user.onboarding_completed:
        from ..services.playbook import seed_from_onboarding

        try:
            profile_dict = updated.profile.model_dump(by_alias=False) if updated.profile else {}
            seed_from_onboarding(user.id, profile_dict)
        except Exception:
            pass
        # M9.3 — first-time onboarding completion captures consent. Idempotent:
        # we never downgrade an existing consent_version.
        if not updated.consent_version:
            store.update_user(
                user.id,
                {
                    "consent_version": CURRENT_CONSENT_VERSION,
                    "consent_given_at": datetime.now(timezone.utc).isoformat(),
                },
            )
            updated = store.get_user(user.id) or updated
    return updated


@router.get("/profile", response_model=BusinessProfile)
async def get_profile(user: User = Depends(get_current_user)):
    return user.profile


@router.get("/profile/completeness")
async def profile_completeness(user: User = Depends(get_current_user)):
    """Per-domain completeness so the Settings UI can nudge the user to fill the
    high-value sections for their business type."""
    # Coerce to the model — some store paths hold profile as a raw JSONB dict.
    p = user.profile if isinstance(user.profile, BusinessProfile) else BusinessProfile(**(user.profile or {}))
    return _profile_completeness(p)


def _has(v) -> bool:
    if v is None:
        return False
    if isinstance(v, str):
        return bool(v.strip())
    if isinstance(v, (list, dict)):
        return len(v) > 0
    return True


def _profile_completeness(p: BusinessProfile) -> dict:
    """Return {percent, sections:{name:bool}} — a section counts as populated if
    any of its meaningful fields is filled."""
    b = p.brand
    c = p.customers
    o = p.operations
    m = p.marketing
    lf = p.legal_financial
    sections = {
        "identity": any(_has(x) for x in (p.display_name, p.role_title, p.industry, p.description)),
        "brand": any(_has(x) for x in (b.mission, b.vision, b.values, b.usp, b.voice, b.style_guidelines)),
        "offerings": _has(p.offerings),
        "customers": any(
            _has(x)
            for x in (
                c.buyer_personas,
                c.industries_served,
                c.locations,
                c.pain_points,
                c.goals,
            )
        ),
        "operations": any(_has(x) for x in (o.team_members, o.working_hours, o.tools, o.workflows, o.sops)),
        "marketing": any(
            _has(x)
            for x in (
                m.competitors,
                m.channels,
                m.social_accounts,
                m.testimonials,
                m.case_studies,
                m.sales_scripts,
            )
        ),
        "legalFinancial": any(
            _has(x)
            for x in (
                lf.registration_details,
                lf.tax_info,
                lf.invoicing_preferences,
                lf.payment_methods,
                lf.contract_notes,
            )
        ),
        "goals": any(
            _has(x)
            for x in (
                p.monthly_revenue_goal,
                p.annual_revenue_goal,
                p.financial_goals,
                p.business_priorities,
            )
        ),
    }
    filled = sum(1 for v in sections.values() if v)
    percent = round(100 * filled / len(sections)) if sections else 0
    return {"percent": percent, "sections": sections}


@router.patch("/profile", response_model=BusinessProfile)
async def update_profile(patch: BusinessProfile, request: Request, user: User = Depends(get_current_user)):
    # Merge only the fields the client actually sent into the existing profile
    # JSONB, so a partial save never wipes other fields.
    sent = await request.json()
    provided = patch.model_dump(mode="json", by_alias=False, include=_provided_keys(patch, sent))
    current = user.profile.model_dump(mode="json", by_alias=False)
    merged = {**current, **provided}
    try:
        updated = store.update_user(user.id, {"profile": merged})
    except Exception as exc:  # most likely: migration not applied
        raise HTTPException(
            status_code=500,
            detail="Could not save profile. Ensure the 'profile' column exists " "(run migrations/2026-05-31_add_user_profile.sql). " + str(exc)[:160],
        )
    if not updated:
        raise HTTPException(status_code=404, detail="User not found")
    return updated.profile


def _provided_keys(model: BusinessProfile, raw: dict) -> set[str]:
    """Map the camelCase keys the client sent to the model's field names, so a
    PATCH only touches those fields."""
    alias_to_field = {f.alias or name: name for name, f in model.model_fields.items()}
    keys = set()
    for k in raw.keys():
        if k in alias_to_field:
            keys.add(alias_to_field[k])
        elif k in model.model_fields:
            keys.add(k)
    return keys
