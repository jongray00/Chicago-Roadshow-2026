"""Static-content guards for the workshop wizard markup in web/index.html.

These do not start a server; they assert on the shipped HTML/JS source so the
wizard's user-facing copy and key behaviors can't silently regress.
"""
import re
from pathlib import Path

import pytest

INDEX = Path(__file__).resolve().parents[1] / "web" / "index.html"


@pytest.fixture(scope="module")
def html() -> str:
    return INDEX.read_text(encoding="utf-8")


def test_no_purchase_confirmation_dialog(html):
    # The "are you sure you want to purchase" confirm() is removed: the user
    # always wants the number, so buying is one click.
    assert "This adds a recurring charge" not in html
    assert "Purchase ${formatPhone(payload.phone_number)} on your SignalWire" not in html
    # Only restartWizard()'s confirm() should remain; no purchase confirm reintroduced.
    assert html.count("confirm(") == 1


def test_versions_not_levels(html):
    # All "Level"/"Lv." wording is replaced by spelled-out "Version N".
    assert "Lv." not in html
    assert "Level up your AI agent" not in html
    assert "level Buddy up" not in html
    # Spelled-out versions are present in STEPS_META.
    assert 'step: "Version 1"' in html
    assert 'step: "Version 2"' in html
    assert "Give Buddy a new capability" in html


def test_open_workshop_button_is_emphasized(html):
    # The primary "Open workshop" CTA carries an explicit large-size class so
    # it reads as the obvious next action.
    assert "btn-cta-lg" in html


def test_area_code_no_results_has_recovery(html):
    # The empty-results branch offers a one-click "show any available number"
    # fallback so an unavailable area code is never a dead end.
    assert 'id="wiz-search-any"' in html
    assert "Show any available US number" in html


def test_manual_point_button_removed_and_autopoint_present(html):
    # The manual per-step "Point my phone number here" button is gone...
    assert "Point my phone number here" not in html
    assert "data-aim-route" not in html
    # ...replaced by automatic re-pointing on version selection.
    assert "function autoPointNumber" in html
    assert "/api/setup/route" in html  # still the endpoint we call


def test_persistent_number_badge_and_call_prompts(html):
    # Each of the four guided versions carries its own curated "call Buddy and
    # ask him" prompt; pin a distinctive phrase from each so a future edit that
    # blanks one is caught.
    assert "callPrompt:" in html
    assert "say hi. Buddy answers" in html                 # Version 1 - Hello Buddy
    assert "the weather in your city" in html              # Version 2 - Buddy Gets a Tool
    assert "the time in Tokyo" in html                     # Version 3 - Buddy Gets Skills
    assert "a dad joke. The full agent" in html            # Version 4 - Complete Buddy
    # Every guided card carries a persistent dial strip with three states:
    # dedicated line (shared mode), your-number-follows (solo), and a
    # never-vanishing empty state. Pin the render fn, the states' copy, the
    # tel: link, and the copy-number action.
    assert "renderDialStrip" in html
    assert "dial-strip" in html
    assert "Dedicated line" in html
    assert "Your number" in html
    assert "No number connected yet" in html
    assert 'href="tel:' in html
    assert "data-orb-route" in html
    assert "Your number dials this version right now." in html
    assert "Select this version and your number follows." in html
    # The sticky pinned badge must know about dedicated per-version numbers,
    # not only the wizard-provisioned one.
    assert "dedicated line" in html


def test_voice_orb_replaces_copy_number(html):
    # The dial strip's action is now a minimal in-card voice-only browser call
    # with a voice-reactive ring; the Copy button is gone (the tel: link stays).
    assert "data-copy-num" not in html
    assert "function renderVoiceOrb" in html
    assert "function bootVoiceOrbs" in html
    assert "cdn.signalwire.com/@signalwire/js" in html   # official UMD bundle, not esm.sh
    assert "function loadSignalWireSDK" in html
    assert "StaticCredentialProvider" in html             # v4 credential-provider construction
    assert "video: false" in html
    assert "createMediaStreamSource" in html      # WebAudio analyser on remoteStream
    assert "orb-canvas" in html
    orb = html.split("function bootVoiceOrbs")[1][:6000]
    assert "hangup" in orb                        # singleton teardown path
    # Audio actually PLAYS (hidden sink element, retargetable by the speaker
    # select), and the live call bar carries both soundwave lanes + devices.
    assert "srcObject" in html
    assert "setSinkId" in html
    assert "ds-callbar" in html
    assert 'data-wave="remote"' in html
    assert 'data-wave="mic"' in html
    assert "updateMicrophone" in html


def test_voice_orb_start_is_race_guarded(html):
    # Overlapping orbStart calls (click orb B while orb A is still connecting)
    # must not orphan A's call: each start claims a generation token and
    # re-checks it after every await, tearing down its own locals when
    # superseded. orbStop also bumps the generation to invalidate in-flight
    # starts.
    start = html.split("async function orbStart")[1].split("async function orbStop")[0]
    assert "++_voiceOrb.gen" in start             # claims a new generation
    assert "myGen" in start                       # local token compared after awaits
    assert start.count("stale()") >= 4            # re-checked after each await
    stop = html.split("async function orbStop")[1][:400]
    assert "_voiceOrb.gen++" in stop              # stop invalidates in-flight starts


def test_browser_call_uses_c2c_widget(html):
    assert "sw-click-to-call" in html
    assert "@signalwire/web-components" in html
    assert "/api/relay/config" in html          # token still minted server-side
    assert "sw-call-ended" in html              # feed + modal handoff wiring
    assert 'id="live-wire"' in html
    assert "/static/live-wire.js" in html
    assert "renderLiveWire" in html


def test_buddy_video_fully_removed(html):
    assert "buddy-video" not in html
    assert "BuddyVideo" not in html
    assert not (pathlib.Path(__file__).resolve().parent.parent / "web" / "buddy-video.js").exists()
    assert "cf-node" not in html                # click-to-reveal diagram gone


def test_presenter_script_banner_removed(html):
    # The 🎤 SAY presenter banner was removed (2026-06-11): no script data,
    # no render block, no CSS class — versions stay.
    version_count = len(re.findall(r'step:\s*"Version \d+"', html))
    assert version_count == 4
    assert "presenterScript" not in html
    assert "presenter-script" not in html
    assert "🎤" not in html


def test_doc_links_are_relative_paths(html):
    # Every STEPS_META docs url must be a relative path (prefixed by DOCS_BASE),
    # never a hardcoded developer.signalwire.com link.
    assert "developer.signalwire.com" not in html
    urls = re.findall(r'url:\s*"(/[^"]+)"', html)
    assert urls, "expected relative doc urls in STEPS_META"


def test_tour_and_hint_dots_removed(html):
    # The 4-callout coachmark tour + pink "?" hint dots were removed (2026-06-11).
    assert "tour.js" not in html
    assert "WorkshopTour" not in html
    assert "sdkworkshop.tourSeen" not in html
    assert "tour-replay" not in html
    assert "hint-dot" not in html
    assert not (pathlib.Path(__file__).resolve().parent.parent / "web" / "tour.js").exists()


def test_dial_strip_replaces_call_cta(html):
    # The dial strip replaced the old pink .step-call-cta banner (2026-07-01).
    # It uses the primary blue family (rgba(4,78,244,…)) so the phone line reads
    # as the card's action, distinct from the pink "important parts" panels,
    # and it pulses only on the active card with reduced-motion respected.
    assert "step-call-cta" not in html
    m = re.search(r"\.dial-strip \{[^}]*\}", html)
    assert m, "dial-strip CSS missing"
    css = m.group(0).replace(" ", "")
    assert "4,78,244" in css
    assert "prefers-reduced-motion" in html


def test_postprompt_modal_present(html):
    assert 'id="postprompt-modal"' in html
    assert 'id="open-postprompt"' in html
    assert "/api/postprompt/final" in html
    # handoff into the browser-call section:
    assert 'id="postprompt-next"' in html


def test_postprompt_open_is_delegated(html):
    # #open-postprompt is rendered dynamically inside #app and recreated on every
    # workshop re-render, so a one-time getElementById().addEventListener at load
    # silently misses it. The open trigger MUST be bound via event delegation on a
    # static ancestor (document) so it survives re-renders.
    assert ('closest("#open-postprompt")' in html
            or "closest('#open-postprompt')" in html), \
        "post-prompt open must use document-level delegation, not a load-time direct binding"


def test_status_banners_present(html):
    assert 'id="api-ticker"' in html
    assert 'id="bottom-right-stack"' in html
    assert 'id="api-log"' in html


def test_state_flow_wired_in_modal(html):
    assert "state-flow.js" in html
    assert "mermaid" in html.lower()
    assert 'id="postprompt-stateflow"' in html


def test_postprompt_review_action_present(html):
    # "See what Buddy captured" is a secondary review action in the finale
    # section (it auto-opens after a browser call ends; see _browserCallEnded).
    # It is intentionally NOT a pulsing primary button in the redesign.
    assert 'id="open-postprompt"' in html        # the review button exists
    assert "#open-postprompt {" in html          # dedicated styling rule
    assert "See what Buddy captured" in html      # its label
    assert "callhub-review" in html               # lives in the call-hub review row


import pathlib
def test_admin_has_state_flow_subtab():
    admin = pathlib.Path("web/admin.html").read_text(encoding="utf-8")
    assert "state-flow.js" in admin
    assert 'data-sub="state-flow"' in admin
    assert 'id="sv-stateflow"' in admin


def test_dashboard_timeline_assets_referenced(html):
    assert "metrics.js" in html and "timeline.js" in html
    assert 'id="postprompt-dashboard"' in html
    assert 'id="postprompt-timeline"' in html


def test_admin_has_dashboard_timeline_subtabs():
    admin = pathlib.Path("web/admin.html").read_text(encoding="utf-8")
    assert "metrics.js" in admin and "timeline.js" in admin
    assert 'data-sub="dashboard"' in admin and 'id="sv-dashboard"' in admin
    assert 'data-sub="timeline"' in admin and 'id="sv-timeline"' in admin


def test_no_local_renderTimeline_shadows_global(html):
    # index.html must NOT declare a top-level `function renderTimeline` — it would
    # overwrite window.renderTimeline (the swimlane renderer from timeline.js) and
    # break the modal Timeline. The progress-UI function is renderStepTimeline.
    assert "function renderTimeline(" not in html
    assert "renderStepTimeline" in html


ADMIN = pathlib.Path(__file__).resolve().parent.parent / "web" / "admin.html"
CHARTS_JS = pathlib.Path(__file__).resolve().parent.parent / "web" / "charts.js"
LIVE_WIRE_JS = pathlib.Path(__file__).resolve().parent.parent / "web" / "live-wire.js"


@pytest.fixture(scope="module")
def admin_html() -> str:
    return ADMIN.read_text(encoding="utf-8")


def test_charts_js_exists_and_exports_renderer():
    src = CHARTS_JS.read_text(encoding="utf-8")
    assert "renderCharts" in src
    assert "latency_breakdown" in src and "swaig_by_command" in src


def test_admin_has_charts_subtab_and_wiring(admin_html):
    assert 'data-sub="charts"' in admin_html
    assert 'id="sv-charts"' in admin_html
    assert "chart.umd.min.js" in admin_html
    assert "/static/charts.js" in admin_html
    assert "renderCharts" in admin_html


def test_index_modal_has_charts_section(html):
    assert 'id="postprompt-charts"' in html
    assert "chart.umd.min.js" in html
    assert "/static/charts.js" in html
    assert "renderCharts" in html


def test_admin_transcript_has_filters_and_badges(admin_html):
    assert 'id="tr-filters"' in admin_html       # filter bar
    assert 'data-trrole="user"' in admin_html    # role chips
    assert 'id="tr-search"' in admin_html        # search box
    assert 'id="tr-rating"' in admin_html        # rating dropdown
    assert "renderTranscriptList" in admin_html  # re-render on filter change
    assert "turn-badges" in admin_html           # badge row class


def test_admin_summary_has_postprompt_three_tabs(admin_html):
    for tab in ('data-pp="raw"', 'data-pp="substituted"', 'data-pp="parsed"'):
        assert tab in admin_html
    assert 'id="pp-tab-body"' in admin_html


JSON_TREE_JS = pathlib.Path(__file__).resolve().parent.parent / "web" / "json-tree.js"


def test_json_tree_module_exists():
    src = JSON_TREE_JS.read_text(encoding="utf-8")
    assert "jsonTreeHtml" in src and "renderJsonTree" in src
    assert "<details" in src        # native collapse/expand


def test_admin_swaig_uses_json_trees(admin_html):
    assert "/static/json-tree.js" in admin_html
    assert "jsonTreeHtml" in admin_html
    assert "post_response" in admin_html      # raw swaig_log surfaced
    assert "swaig-actions" in admin_html      # action[] badges


GLOBAL_DATA_JS = pathlib.Path(__file__).resolve().parent.parent / "web" / "global-data.js"


def test_global_data_module_exists():
    src = GLOBAL_DATA_JS.read_text(encoding="utf-8")
    assert "renderGlobalData" in src and "jsonTreeHtml" in src


def test_admin_has_global_data_subtab(admin_html):
    assert 'data-sub="global-data"' in admin_html
    assert 'id="sv-globaldata"' in admin_html
    assert "/static/global-data.js" in admin_html
    assert "renderGlobalData" in admin_html


RECORDING_JS = pathlib.Path(__file__).resolve().parent.parent / "web" / "recording.js"


def test_recording_module_exists():
    src = RECORDING_JS.read_text(encoding="utf-8")
    assert "renderRecording" in src
    assert "WaveSurfer" in src
    assert "<audio" in src          # graceful fallback


def test_admin_has_recording_subtab(admin_html):
    assert 'data-sub="recording"' in admin_html
    assert 'id="sv-recording"' in admin_html
    assert "wavesurfer" in admin_html        # CDN tag
    assert "/static/recording.js" in admin_html
    assert "renderRecording" in admin_html


def test_no_event_branding_in_user_facing_surfaces():
    """The app is a city-agnostic SDK workshop: no Chicago/Roadshow/meetup
    strings may appear in served web assets."""
    import re
    web = pathlib.Path(__file__).resolve().parent.parent / "web"
    banned = re.compile(r"chicago|roadshow|meetup", re.IGNORECASE)
    offenders = []
    for f in sorted(web.glob("*.html")) + sorted(web.glob("*.js")):
        for n, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            if banned.search(line):
                offenders.append(f"{f.name}:{n}: {line.strip()[:100]}")
    assert not offenders, "event branding leaked:\n" + "\n".join(offenders)


def test_live_wire_module():
    src = LIVE_WIRE_JS.read_text(encoding="utf-8")
    assert "renderLiveWire" in src
    assert "injectLocal" in src
    assert "/api/live-events" in src
    assert "EventSource" in src


def test_c2c_section_is_static_and_boot_once(html):
    # The #cf-section must be a single static element outside the renderWorkshop
    # template — so re-renders never destroy an active call widget.
    assert '_c2cBooted' in html, "_c2cBooted boot-once flag missing"
    # Exactly one id="cf-section" in the whole file.
    assert html.count('id="cf-section"') == 1, "cf-section must appear exactly once"
    # The static section must carry the hidden attribute in the markup.
    # (Its class is "finale" since the curriculum-collapse redesign; the id and
    # static/boot-once nature are what this test guards.)
    assert 'id="cf-section" hidden' in html, \
        "static cf-section must start hidden"
    # The section must NOT appear inside the renderWorkshop template string.
    # Find the renderWorkshop template (between the backtick after app.innerHTML
    # and the closing backtick) and assert cf-section is absent from it.
    import re
    # Locate the renderWorkshop function body
    rw_match = re.search(r'function renderWorkshop\(\)(.*?)^function \w', html,
                         re.DOTALL | re.MULTILINE)
    assert rw_match, "renderWorkshop function not found"
    rw_body = rw_match.group(1)
    assert 'id="cf-section"' not in rw_body, \
        "cf-section must NOT be inside the renderWorkshop template"


def test_live_wire_closes_previous_eventsource():
    src = LIVE_WIRE_JS.read_text(encoding="utf-8")
    assert "es.close()" in src, "renderLiveWire must close the previous EventSource on re-call"


def test_finale_is_static_below_call_section_and_retriggered(html):
    # The grand finale + workshop footer moved out of the re-rendered #app
    # (2026-06-11): static siblings ordered call-section -> finale -> footer,
    # revealed via the browser-call -> post-prompt-modal-close path.
    assert html.count('id="grand-finale"') == 1
    assert html.count('id="workshop-footer"') == 1
    main_end = html.index("</main>")
    assert html.index('id="grand-finale"') > main_end
    assert html.index('id="cf-section"') < html.index('id="grand-finale"')
    assert html.index('id="grand-finale"') < html.index('id="workshop-footer"')
    assert "_browserCallEnded" in html
    # showGrandFinale is invoked somewhere beyond its definition
    assert html.count("showGrandFinale(") >= 2


def test_web_components_embed_is_version_pinned(html):
    # The unpinned unpkg URL serves 'latest'; 4.0.0-rc.0 introduced a remote
    # <video muted> regression that silences the agent entirely. Pin to
    # 4.0.0-beta.12 (last build whose remote media element is unmuted) so a
    # future 'latest' can't silently change call behavior mid-workshop.
    m = re.search(r'unpkg\.com/@signalwire/web-components@([^/"]+)/', html)
    assert m, "web-components embed script URL must be version-pinned"
    assert m.group(1) == "4.0.0-beta.12"


def test_hero_is_signalwire_ai_workshop(html):
    # The old login-first entry hero ("SignalWire AI Workshop" / "as easy as
    # 1,2,3") is gone: renderLanding's "Meet Buddy" hero is the sole entry
    # point now, and renderOnboarding was reskinned as the number flow
    # (Task 7). Guard both banned copies stay gone.
    assert "SignalWire <span class=\"accent\">AI Workshop</span>" not in html
    assert "Build your first <span class=\"accent\">AI phone agent</span>" not in html
    assert "Setup for this Workshop is as easy as 1,2,3" not in html


def test_wizard_leads_deleted(html):
    assert "Your credentials are the keys" not in html
    assert "A phone number is how people reach Buddy" not in html
    assert "Dial it from any phone. Buddy picks up." in html
    assert "An AI agent can be reached two ways" not in html


def test_workshop_top_band_collapsed(html):
    assert "You're up and running." not in html
    assert "Advanced: use your own number" in html
    assert "Each version adds one. Click any node to switch. Your number follows." in html


def test_steps_meta_copy_budgets(html):
    import re
    block = html[html.index("const STEPS_META"):html.index("PILLAR_CARDS")]
    # The writing rules apply to card/callout COPY, not to the verbatim Python
    # we embed for the early agents. Strip fullCode template literals first so a
    # real source line that happens to contain "just"/"—" isn't penalized. The
    # literal can itself contain escaped backticks (e.g. `step_change` in a
    # comment), so consume escaped chars rather than stopping at the first `.
    block = re.sub(r"fullCode:\s*`(?:\\.|[^`])*`", "", block)
    assert "—" not in block, "em-dashes are banned in card copy"
    assert not re.search(r"\bjust\b", block), "'just' is banned in card copy"
    for m in re.finditer(r'desc: "([^"]+)"', block):
        assert len(m.group(1).split()) <= 16, f"lead too long: {m.group(1)}"


def test_annotated_code_present(html):
    assert "function renderAnnotatedCode" in html
    assert "function wireAnnotatedCode" in html
    assert "renderAnnotatedCode(step" in html          # called from renderStepSection
    assert "annotated-code" in html and "ac-callout" in html and "ac-marker" in html
    assert ".spotlight" in html


def test_build_along_removed(html):
    # the game mechanic is gone
    assert "renderCodeBuildAlong" not in html
    assert "wireBuildAlong" not in html
    assert "ba-level" not in html
    assert "state.buildAlong" not in html
    assert "sdkworkshop.buildAlong" not in html


def test_every_step_has_callouts(html):
    # all 4 steps carry a callouts array. Every step now embeds its FULL real
    # .py source via fullCode (the "wow, that's the whole agent?" reveal), so
    # the intent is "every step still has real code".
    assert html.count("callouts:") >= 4
    assert html.count("fullCode:") >= 4


def test_full_code_verbatim_not_escaped(html):
    block = html[html.index("const STEPS_META"):html.index("PILLAR_CARDS")]
    # full code is embedded raw, not HTML-escaped (the &#39; double-escape bug)
    assert "&#39;" not in block and "&quot;" not in block and "&amp;" not in block
    # drift guard: a real line from each agent is present verbatim
    assert "class HelloAgent(AgentBase):" in html
    assert "def on_tell_joke" in html and "icanhazdadjoke.com" in html
    assert "self.define_contexts()" in html and "register_weather_tool(self)" in html


def _steps_meta_block(html: str) -> str:
    return html[html.index("const STEPS_META"):html.index("PILLAR_CARDS")]


def test_callouts_trimmed(html):
    # Every callouts array carries between 2 and 4 entries: enough to teach the
    # key ideas, few enough not to overwhelm.
    block = _steps_meta_block(html)
    arrays = re.findall(r"callouts:\s*\[(.*?)\]", block, re.DOTALL)
    assert len(arrays) >= 4, "expected a callouts array per step"
    for arr in arrays:
        n = len(re.findall(r"\{\s*id:", arr))
        assert 2 <= n <= 4, f"callouts array has {n} entries (want 2-4): {arr[:120]}"


def test_reduced_motion_block_present(html):
    assert "prefers-reduced-motion" in html


def test_shared_mode_hides_restart_wizard(html):
    # The status pill must branch on shared mode: a reset-progress button instead
    # of restart-wizard (which would drop a shared attendee into the number wizard).
    # The pill carries its own id (reset-progress-pill) so it never collides with
    # the static footer's reset-progress-link button and steal its binding.
    assert 'id="reset-progress-pill"' in html
    assert "_account?.shared" in html or "_account || {}).shared" in html
    # The shared-mode ternary renders the pill id, not the footer's id.
    ternary = html[html.index("(window._account || {}).shared === true"):]
    ternary = ternary[:ternary.index("restart-wizard-link")]
    assert "reset-progress-pill" in ternary
    assert "reset-progress-link" not in ternary
    # The footer's all-modes reset button and both wirings stay intact.
    assert 'id="reset-progress-link"' in html
    assert 'getElementById("reset-progress-link")' in html
    assert 'getElementById("reset-progress-pill")' in html


def test_render_all_guards_shared_mode_onboarding(html):
    # renderAll routes: landing when not started; the number wizard ONLY via
    # the transient gettingNumber flag, and never in shared mode.
    body = html.split("function renderAll()")[1][:900]
    assert "renderLanding" in body
    assert "gettingNumber" in body
    assert '_account?.shared !== true' in body


def test_autopoint_noops_in_shared_mode(html):
    assert "sharedDeployment" in html.split("function autoPointNumber")[1][:400]


def test_chip_scoped_label_when_shared_and_connected(html):
    assert "· outbound" in html            # chip label: "acme · outbound"


def test_acct_menu_explains_scope_in_shared_mode(html):
    assert "Build runs on the workshop account" in html


def test_solo_mode_logout_replaces_fake_switch(html):
    assert "Log out" in html
    assert "Confirm log out?" in html


def test_needs_own_account_is_handled(html):
    # Any endpoint can 400 with {needs_own_account:true} (stale session, mode
    # change). swApi must route that centrally instead of leaving raw error
    # text in a corner — assert it's handled in JS, not only documented.
    assert "needs_own_account" in html.split("function swApi")[1][:1200]


def test_no_stale_seven_agents_copy(html):
    assert "Seven agents" not in html
    assert "Four agents. Each adds one new capability." in html


def test_landing_page_start_first(html):
    # The first screen for every mode: Meet Buddy + Start CTA + deferral copy.
    # Login is offered quietly (with a signup companion) but never required.
    assert "function renderLanding" in html
    assert "Start the workshop" in html
    assert "Meet <span class=\"accent\">Buddy</span>" in html
    assert "In the next hour you'll rebuild me from scratch" in html
    assert "No account needed to build." in html
    assert 'id="landing-login-link"' in html
    assert "Create a free Space" in html
    # Buddy's video avatar headlines the hero (same asset the browser call
    # renders), ringed in the rotating brand gradient; the Start CTA carries
    # the brand-gradient btn-start treatment.
    assert "landing-avatar" in html
    assert html.count("robot_idle2.mp4") >= 2   # finale card + landing hero
    assert "btn-start" in html
    assert "la-spin" in html


def test_getting_number_is_transient(html):
    # The number-flow flag must never round-trip through localStorage: a
    # reload lands back in the workshop, not a half-open wizard.
    assert "sdkworkshop.gettingNumber" not in html


def test_landing_hides_static_workshop_sections(html):
    # renderLanding must hide the static workshop-only siblings exactly as
    # renderOnboarding does, so a mid-workshop restart never leaves the call
    # hub / grand finale / footer visible underneath the landing.
    body = html.split("function renderLanding()")[1].split("function startWorkshop()")[0]
    assert 'getElementById("cf-section")' in body
    assert 'getElementById("workshop-footer")' in body
    assert 'getElementById("grand-finale")' in body
    assert "finaleShown = false" in body


def test_connect_drawer_has_signup_callout(html):
    # Requirement: every "Log in with SignalWire" surface carries a signup
    # companion. The drawer is THE login surface, so it gets the loud invite
    # in a compact size.
    drawer = html.split('id="connect-drawer"')[1][:4000]
    assert "signup-invite compact" in drawer
    assert "signalwire.com/signup" in drawer


def test_browser_call_gates_on_login_solo(html):
    # Solo + logged out: the inbound call card asks for login (with signup)
    # instead of erroring. Shared mode is unaffected.
    assert "function renderC2CGate" in html
    assert "Buddy answers this call on your SignalWire Space." in html
    assert 'id="c2c-login-btn"' in html
    gate = html.split("function renderC2CGate")[1][:1500]
    assert "signalwire.com/signup" in gate


def test_dial_strip_solo_gates(html):
    # Solo empty states: logged out -> "Log in" link opens the drawer;
    # logged in without a number -> "Get a number" enters the number flow.
    assert "ds-login-link" in html
    assert "to connect a number, or use the browser call at the end." in html
    assert "ds-number-link" in html
    assert "and it follows the version you're viewing." in html


def test_capstone_connect_has_signup(html):
    block = html.split('id="capstone-connect"')[1][:1200]
    assert "signalwire.com/signup" in block
    assert "Create a free Space" in block


def test_onboarding_is_now_the_number_flow(html):
    # The wizard's login-first hero is gone; renderOnboarding is reachable only
    # as the post-login number flow and is titled accordingly.
    assert "as easy as 1,2,3" not in html
    assert "Connect a <span class=\"accent\">number</span>" in html
    assert "back-to-workshop-link" in html


def test_every_login_surface_has_signup_companion(html):
    # Spec requirement 3: wherever "Log in with SignalWire" appears, a signup
    # callout appears with it. Surfaces: landing, connect drawer, browser-call
    # gate, outbound card, wizard creds step. Census by URL count.
    assert html.count("https://signalwire.com/signup") >= 5
