"""The message of the day: loading, fitting it into the dashboard, and safe HTML for the web page."""
from types import SimpleNamespace

from bot import motd
from bot.embeds import status_embed
from bot.server import ServerState
from bot.store import Store, connect


def test_missing_or_blank_file_means_no_message(tmp_path):
    assert motd.load(str(tmp_path / "nope.md")) is None
    blank = tmp_path / "blank.md"
    blank.write_text("  \n\n")
    assert motd.load(str(blank)) is None


def test_edits_are_picked_up_without_a_restart(tmp_path):
    path = tmp_path / "motd.md"
    path.write_text("first")
    assert motd.load(str(path)) == "first"
    path.write_text("second\n")
    assert motd.load(str(path)) == "second"


def test_long_text_is_cut_to_the_field_limit():
    text = "x" * (motd.FIELD_LIMIT + 50)
    cut = motd.for_embed(text)
    assert len(cut) == motd.FIELD_LIMIT and cut.endswith("…")
    assert motd.for_embed("short") == "short"


def test_html_is_escaped_before_formatting():
    html = motd.to_html("**Hi** <script>x</script>\n- one\n• two\n`seed`")
    assert html == ("<b>Hi</b> &lt;script&gt;x&lt;/script&gt;<br>• one<br>• two<br><code>seed</code>")


def embed_fields(tmp_path, text, dashboard):
    path = tmp_path / "motd.md"
    path.write_text(text)
    cfg = SimpleNamespace(server_name="Midgard", join_address="1.2.3.4:2456", world_dir=str(tmp_path),
                          motd_file=str(path))
    embed = status_embed(cfg, ServerState(), Store(connect(":memory:")), join_steps_field=dashboard)
    return [(field.name, field.value) for field in embed.fields]


def test_dashboard_shows_the_message_before_the_join_steps(tmp_path):
    names = [name for name, _ in embed_fields(tmp_path, "Welcome!", dashboard=True)]
    assert names.index("📜 About Midgard") == names.index("🛡️ How to join (whitelist only)") - 1


def test_status_command_and_empty_file_leave_it_out(tmp_path):
    assert all("About" not in name for name, _ in embed_fields(tmp_path, "Welcome!", dashboard=False))
    assert all("About" not in name for name, _ in embed_fields(tmp_path, "", dashboard=True))
