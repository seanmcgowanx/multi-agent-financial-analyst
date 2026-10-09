"""Base Agent class

- every agent subclasses Agent and shares one OpenAI client.
- model defaults to DEFAULT_MODEL; whoever builds an agent picks its model.
- prefer reasoning effort to control outputs over temperature/top-k/top-p

Notes:
- process is the generic entry point used by Coordinator.route and send_to.
  Specialists override it (e.g. to run use_tools or NewsChain) and should
  still append {"task", "result"} to self.memory.
- self.memory is in-session history only. Cross-run memory is memory.py.
- use_tools runs the ReAct-style tool loop: the model replies with
  JSON ({"thought", "tool", "args"} or {"final"}), the tool runs from
  tools.TOOLS, and the observation is fed back, up to config.MAX_TOOL_STEPS.
"""

import json

from multi_agent.config import DEFAULT_MODEL, MAX_TOOL_STEPS, client
from multi_agent.prompts import TOOL_PROTOCOL
from multi_agent.tools import TOOLS


class Agent:
    def __init__(
        self,
        name,
        role,
        model=DEFAULT_MODEL,
        tools=None,
    ):
        self.name = name
        self.role = role
        self.model = model
        self.tools = tools or []  # names of TOOLS this agent may call
        self.memory = []  # in-session history of {"task", "result"}

    def call_llm(self, prompt, max_tokens=None, reasoning_effort=None, json_mode=False):
        # Reasoning effort and max_tokens only sent to api when set
        kwargs = {}
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        if reasoning_effort:
            kwargs["reasoning_effort"] = reasoning_effort
        if max_tokens:
            kwargs["max_completion_tokens"] = max_tokens

        try:
            response = client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": f"You are {self.name}, a {self.role} agent.",
                    },
                    {"role": "user", "content": prompt},
                ],
                **kwargs,
            )
        except Exception as e:
            print(f"API failed for {self.name}: {e}")
            raise

        return response.choices[0].message.content

    def process(self, task):
        prompt = f"As a {self.role}, {task}"
        result = self.call_llm(prompt)
        self.memory.append({"task": task, "result": result})
        return result

    def send_to(self, other_agent, message):

        print(f"{self.name} -> {other_agent.name}: {message[:40]}...")
        return other_agent.process(f"Process this from {self.name}: {message}")

    def use_tools(self, task, reasoning_effort=None):
        """ReAct loop: the model picks a tool, we run it, and feed back the result.

        Returns the final answer. The steps (thought, tool, args, result) are
        kept in self.last_trace so the notebook can show the agent's decisions.
        """
        descriptions = "\n".join(f"- {TOOLS[n]['description']}" for n in self.tools)
        protocol = TOOL_PROTOCOL.format(tool_descriptions=descriptions)
        self.last_trace = []

        for _ in range(MAX_TOOL_STEPS):
            history = "\n".join(json.dumps(step) for step in self.last_trace)
            prompt = f"{protocol}\n\nTask: {task}\n\nSteps so far:\n{history or 'none'}"
            raw = self.call_llm(
                prompt, reasoning_effort=reasoning_effort, json_mode=True
            )

            try:
                reply = json.loads(raw)
            except json.JSONDecodeError:
                self.last_trace.append({"error": f"Invalid JSON reply: {raw[:200]}"})
                continue

            if "final" in reply:
                self.memory.append({"task": task, "result": reply["final"]})
                return reply["final"]

            name, args = reply.get("tool"), reply.get("args", {})
            if name not in self.tools:
                result = f"Unknown tool {name!r}. Available: {self.tools}"
            else:
                try:
                    result = TOOLS[name]["fn"](**args)
                except Exception as e:  # noqa: BLE001 -- any tool failure goes back to the model
                    result = f"Tool error: {e}"

            self.last_trace.append(
                {
                    "thought": reply.get("thought"),
                    "tool": name,
                    "args": args,
                    "result": result,
                }
            )

        # If max steps is reached, ask for a final answer from what was gathered
        history = "\n".join(json.dumps(step) for step in self.last_trace)
        final = self.call_llm(
            f"Task: {task}\n\nTool results:\n{history}\n\n"
            "Answer the task using only these results.",
            reasoning_effort=reasoning_effort,
        )
        self.memory.append({"task": task, "result": final})
        return final
