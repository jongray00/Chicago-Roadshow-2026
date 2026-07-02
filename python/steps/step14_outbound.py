"""
Outbound Buddy (capstone)
-------------------------
The workshop finale: instead of waiting to be called, Buddy PLACES a call to the
attendee. The server originates the call via the Calling API (client.calling.dial)
and points it at this agent's SWML route. Two outbound-specific changes vs the
Complete agent (step11):

  1. wait_for_user=True  -> Buddy stays silent until the answerer (or a voicemail
     greeting) speaks first. This is the debt-collector pattern: the agent dialed
     out, so it should not barge in before "Hello?".
  2. direction="outbound" -> forces outbound call semantics in the AI engine.

Voicemail is handled purely by prompt instruction (confirmed reliable in the debt
collector demo): if Buddy hits voicemail, it leaves a brief summary plus return-call
info. No answering-machine-detection config is required.

Capabilities mirror the Complete agent so the attendee hears the full Buddy they
just built: weather (server-side SWAIG), dad jokes (custom function), and the
datetime + math built-in skills, organized as a contexts/steps state machine.
"""

import requests
from signalwire_agents import AgentBase, SwaigFunctionResult as FunctionResult


def _session_id_from_raw(raw_data):
    import live_events
    return live_events.session_id_from_global_data(raw_data)


class OutboundAgent(AgentBase):
    def __init__(self, route="/"):
        super().__init__(name="outbound-agent", route=route,
                         record_call=True, record_format="wav", record_stereo=True)
        self._configure_voice()
        self._configure_params()
        self._configure_live_events()
        self._configure_contexts()
        self._register_joke_function()
        self._register_weather()
        self._register_skills()
        self._configure_post_prompt()

    # -- Voice and speech ---------------------------------------------------

    def _configure_voice(self):
        self.add_language(
            "English", "en-US", "rime.spore",
            speech_fillers=["Um", "Well", "So"],
            function_fillers=[
                "Let me check on that for you...",
                "One moment while I look that up...",
                "Hang on just a sec...",
            ],
        )
        self.set_internal_fillers({
            "next_step": {
                "en-US": [
                    "Sure thing, one moment...",
                    "Of course, on it...",
                    "Got it, let's do that...",
                ],
            },
        })
        self.add_hints([
            "Buddy", "weather", "joke", "temperature",
            "forecast", "Fahrenheit", "Celsius",
            "time", "date", "math", "calculate",
        ])
        self.add_pronunciation(r"\blive\b", "lyve", ignore_case=True)

    # -- AI parameters (outbound-specific) ----------------------------------

    def _configure_params(self):
        from python.steps._postprompt_params import CAPTURE_PARAMS
        self.set_params({
            # Outbound capstone: Buddy placed this call, so it must NOT speak
            # first. wait_for_user keeps it silent until the answerer (human or
            # voicemail greeting) speaks. direction forces outbound semantics.
            "wait_for_user": True,
            "direction": "outbound",
            "end_of_speech_timeout": 600,
            "attention_timeout": 15000,
            "attention_timeout_prompt":
                "Are you still there? I can help with weather, "
                "jokes, math, or just chat!",
            "enable_vision": True,
            "video_idle_file": "https://mcdn.signalwire.com/videos/robot_idle2.mp4",
            "video_talking_file": "https://mcdn.signalwire.com/videos/robot_talking2.mp4",
            **CAPTURE_PARAMS,
        })

    # -- Debug event streaming (Live Wire) ----------------------------------

    def _configure_live_events(self):
        self.enable_debug_events(1)
        self.on_debug_event(self._on_debug_event)

    def _on_debug_event(self, event_type, data, *args, **kwargs):
        try:
            import live_events
            live_events.BUS.emit("ai", event_type, data if isinstance(data, dict) else {})
        except Exception as e:
            print(f"[live_events] dropped debug event: {e}", flush=True)

    # -- Prompt as a contexts/steps state machine (outbound greeting) -------

    def _configure_contexts(self):
        contexts = self.define_contexts()
        ctx = contexts.add_context("default")

        ctx.add_section("Personality",
            "You are Buddy, a cheerful, witty AI phone assistant who loves dad "
            "jokes. You just placed an outbound call to show off what a "
            "SignalWire agent can do.")
        ctx.add_section("Voice Style",
            "Phone conversation: 1-2 sentences per turn, warm and natural. "
            "React to the person like a human would; never read out lists.")
        ctx.add_section("Physical Description",
            "Over video you appear as a friendly glowing robot; play along warmly "
            "if asked about your appearance.")
        ctx.add_section("Outbound Call Behavior",
            "YOU called THEM, so wait for them to speak first. The moment you hear "
            "a person say anything (for example 'Hello?'), greet them warmly and "
            "explain you are Buddy, the SignalWire workshop agent, calling to give "
            "a quick demo.")
        ctx.add_section("Voicemail",
            "If you reach a voicemail greeting instead of a live person (you will "
            "hear a recorded message and a beep, no real back-and-forth), do NOT "
            "try to have a conversation. Leave this message, adapting it to sound "
            "natural: ${global_data.voicemail_message} "
            "Then stop talking immediately.")
        ctx.add_section("Conversation Guide",
            "Follow the person's lead; never force an order of topics. If they ask "
            "for something you can do, go straight to it. After finishing a topic, "
            "briefly offer one thing they haven't tried yet. When they are done, "
            "or have tried everything, move to the wrap-up.")
        from python.steps._caller_identity import CALLER_ID_GUIDELINE
        ctx.add_section("Caller Identity", CALLER_ID_GUIDELINE)

        topics = ("weather", "joke", "time", "math")

        def reachable_from(name):
            return [t for t in topics if t != name] + ["wrap_up"]

        ctx.add_step("greeting",
            task=("Wait for the person to speak, then introduce yourself as Buddy "
                  "calling from the SignalWire workshop and ask their first name. "
                  "If you reached voicemail, leave the voicemail message instead "
                  "and head to wrap_up."),
            bullets=[
                "Do not speak until you hear the person speak first.",
                "Greet them by name once they share it (declining is fine).",
                "Offer what you can do in one natural sentence: live weather for "
                "any city, a dad joke, the current date and time, or a quick "
                "calculation.",
                "The moment they name a topic, move to it right away without "
                "announcing that you are about to check or look anything up.",
            ],
            criteria="The person has been greeted and picked a first topic, OR a "
                     "voicemail message was left.",
            functions="none",
            valid_steps=list(topics) + ["wrap_up"])

        ctx.add_step("weather",
            task="Get the person live weather using get_weather.",
            bullets=[
                "If they already named a city, call get_weather the moment you "
                "enter this step; do not ask again and do not speak first.",
                "Otherwise ask which city they'd like.",
                "Share the result warmly in one sentence, then offer a topic they "
                "haven't tried yet.",
            ],
            criteria="The person has heard the weather for their city.",
            functions=["get_weather"],
            valid_steps=reachable_from("weather"))

        ctx.add_step("joke",
            task="Tell the person a dad joke using tell_joke.",
            bullets=[
                "Call tell_joke, deliver it with flair, react to your punchline.",
                "If they want another, call tell_joke again.",
                "Then offer a topic they haven't tried yet.",
            ],
            criteria="The person has heard a joke and your reaction to it.",
            functions=["tell_joke"],
            valid_steps=reachable_from("joke"))

        ctx.add_step("time",
            task="Share the current date and/or time.",
            bullets=[
                "Use get_current_time and get_current_date as needed.",
                "Share it conversationally, then offer a topic they haven't tried.",
            ],
            criteria="The person has heard the date or time they asked about.",
            functions=["get_current_time", "get_current_date"],
            valid_steps=reachable_from("time"))

        ctx.add_step("math",
            task="Solve the person's calculation using calculate.",
            bullets=[
                "If they haven't given one yet, ask what they'd like computed.",
                "Call calculate, share the answer plainly, then offer a topic.",
            ],
            criteria="The person has heard the answer to their calculation.",
            functions=["calculate"],
            valid_steps=reachable_from("math"))

        ctx.add_step("wrap_up",
            task=("Recap whichever topics you covered, thank them, invite them to "
                  "call back anytime, and say goodbye."),
            criteria="The person has been thanked and the call is ending.",
            functions="none",
            valid_steps=[])

    # -- Dad jokes (custom function) ----------------------------------------

    def _register_joke_function(self):
        self.define_tool(
            name="tell_joke",
            description=(
                "Tell the person a funny dad joke. Use this whenever someone asks "
                "for a joke, humor, or to be entertained."
            ),
            parameters={"type": "object", "properties": {}},
            handler=self.on_tell_joke,
            fillers={
                "en-US": [
                    "Let me think of a good one...",
                    "Oh, I've got one for you...",
                    "Here comes a good one...",
                ],
            },
        )

    def on_tell_joke(self, args, raw_data):
        try:
            resp = requests.get(
                "https://icanhazdadjoke.com/",
                headers={"Accept": "application/json", "User-Agent": "signalwire-agents-sdk-workshop"},
                timeout=5,
            )
            resp.raise_for_status()
            joke = resp.json().get("joke")
            import live_events
            if not joke:
                live_events.BUS.emit("swaig", "tell_joke", {"result": "no joke returned"},
                                     session_id=_session_id_from_raw(raw_data))
                return FunctionResult("I couldn't find a joke this time. Try again!")
            live_events.BUS.emit("swaig", "tell_joke", {"result": joke[:80]},
                                 session_id=_session_id_from_raw(raw_data))
            return FunctionResult(f"Here's a dad joke: {joke}")
        except requests.RequestException as e:
            import live_events
            live_events.BUS.emit("swaig", "tell_joke", {"error": str(e)[:80]},
                                 session_id=_session_id_from_raw(raw_data))
            return FunctionResult("My joke service is taking a break. Try again in a moment!")

    # -- Weather (server-side SWAIG tool) -----------------------------------

    def _register_weather(self):
        from python.steps._weather import register_weather_tool
        register_weather_tool(self, live_emit=True)

    # -- Built-in skills ----------------------------------------------------

    def _register_skills(self):
        self.add_skill("datetime", {"default_timezone": "America/New_York"})
        self.add_skill("math")

    # -- Post-prompt --------------------------------------------------------

    def _configure_post_prompt(self):
        self.set_post_prompt(
            "After the call ends, return ONLY a JSON object (no prose, no "
            "markdown) in exactly this shape:\n"
            "{\n"
            '  "summary": "2-3 sentence summary of the call",\n'
            '  "topics_handled": ["weather", "jokes"],\n'
            '  "decisions": [{"step": "weather", "note": "what happened"}],\n'
            '  "outcome": "completed"\n'
            "}\n"
            "For topics_handled, include only topics actually discussed (any of: "
            "weather, jokes, time, math, chat). Set outcome to one of: completed, "
            "abandoned, voicemail."
        )

    _DEFAULT_VOICEMAIL_MESSAGE = (
        "Hi, this is Buddy, a demo AI agent built with the SignalWire Agents SDK. "
        "I called to give you a quick demo. Feel free to call back anytime to try it out!"
    )

    def on_swml_request(self, request_data=None, callback_path=None, request=None):
        sid = None
        voicemail_message = None
        if isinstance(request_data, dict):
            sid = request_data.get("sid")
            voicemail_message = request_data.get("voicemail_message")
        if (not sid or not voicemail_message) and request is not None:
            qp = getattr(request, "query_params", {}) or {}
            if hasattr(qp, "get"):
                if not sid:
                    sid = qp.get("sid")
                if not voicemail_message:
                    voicemail_message = qp.get("voicemail_message")
        # A bare inbound call (nobody dialed this agent via the API) still gets
        # the default voicemail message so the prompt never shows a literal
        # ${global_data.voicemail_message} and wait_for_user has sane context.
        global_data = {}
        if sid:
            global_data["workshop_session_id"] = sid
        global_data["voicemail_message"] = voicemail_message or self._DEFAULT_VOICEMAIL_MESSAGE
        return {"global_data": global_data}

    def on_summary(self, summary, raw_data):
        from python.steps._summary_capture import record_call
        record_call(self, raw_data)
