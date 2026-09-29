"""The OAuth return page: every refusal path, the success path, and HTML escaping.

Discord's API is replaced by a fake identity, so no network is used.
"""
import asyncio
from types import SimpleNamespace

import pytest

from bot.store import connect
from bot.web import OAuth, OAuthStates
from bot.whitelist import Whitelist

ALLOWED, OTHER = 1, 2
ALICE, BOB = 111, 222
STEAM = "76561198000000002"


class FakeGuild:
    async def fetch_member(self, discord_id):
        return f"member{discord_id}"


@pytest.fixture
def setup(tmp_path):
    db = connect(":memory:")
    listfile = tmp_path / "permittedlist.txt"
    listfile.write_text("")
    whitelist = Whitelist(db, str(listfile))
    states = OAuthStates(db)
    motd = tmp_path / "motd.md"
    motd.write_text("**Welcome!** No raids.\n- be kind")
    cfg = SimpleNamespace(public_url="https://example", server_name="Midgard", join_address="1.2.3.4:2456",
                          allowed_guilds=frozenset({ALLOWED}), client_secret="secret", motd_file=str(motd))
    client = SimpleNamespace(get_guild=lambda guild_id: FakeGuild() if guild_id == ALLOWED else None)
    oauth = OAuth(client, whitelist, states, cfg, client_id=42)
    return SimpleNamespace(oauth=oauth, whitelist=whitelist, states=states, listfile=listfile)


def identity(user_id=ALICE, steam=({"type": "steam", "verified": True, "id": STEAM, "name": "Alice"},)):
    return SimpleNamespace(user_id=str(user_id), connections=list(steam))


def visit(setup, query, who=None):
    """Load the callback page; `who` is the identity Discord would return for the code."""
    async def fetch_identity(code):
        return who or identity()
    setup.oauth._fetch_identity = fetch_identity
    response = asyncio.run(setup.oauth.callback(SimpleNamespace(query=query)))
    return response.status, response.text


def link(setup, discord_id=ALICE, guild_id=ALLOWED):
    return {"code": "c", "state": setup.states.create(discord_id, guild_id)}


def test_cancelled_on_discord(setup):
    status, page = visit(setup, {"error": "access_denied"})
    assert status == 200 and "Cancelled" in page


def test_unknown_or_used_link(setup):
    assert visit(setup, {"code": "c", "state": "forged"})[0] == 400
    query = link(setup)
    assert visit(setup, query)[0] == 200
    status, page = visit(setup, query)  # a link works only once
    assert status == 400 and "Link expired" in page


def test_link_from_a_server_that_is_not_allowed(setup):
    assert visit(setup, link(setup, guild_id=OTHER))[0] == 403


def test_authorized_with_another_discord_account(setup):
    status, page = visit(setup, link(setup), who=identity(user_id=BOB))
    assert status == 403 and "Wrong Discord account" in page


def test_not_a_member_of_the_server(setup):
    setup.oauth.client = SimpleNamespace(get_guild=lambda guild_id: None)
    assert visit(setup, link(setup))[0] == 403


def test_no_verified_steam_connection(setup):
    unverified = ({"type": "steam", "verified": False, "id": STEAM, "name": "Alice"},)
    status, page = visit(setup, link(setup), who=identity(steam=unverified))
    assert status == 400 and "No Steam account linked" in page
    assert setup.whitelist.entries() == []


def test_steam_account_already_linked_to_someone_else(setup):
    setup.whitelist.link(BOB, "bob", ALLOWED, STEAM, "Alice")
    assert visit(setup, link(setup))[0] == 409


def test_success_whitelists_and_writes_the_file(setup):
    status, page = visit(setup, link(setup))
    assert status == 200 and "on the whitelist!" in page
    assert setup.whitelist.by_discord(ALICE).steamid == STEAM
    assert STEAM in setup.listfile.read_text()
    assert "<b>Welcome!</b> No raids.<br>• be kind" in page  # the message of the day


def test_refusal_pages_do_not_show_the_message_of_the_day(setup):
    assert "Welcome!" not in visit(setup, {"code": "c", "state": "forged"})[1]


def test_steam_name_is_html_escaped(setup):
    evil = ({"type": "steam", "verified": True, "id": STEAM, "name": "<script>alert(1)</script>"},)
    page = visit(setup, link(setup), who=identity(steam=evil))[1]
    assert "<script>" not in page and "&lt;script&gt;" in page
