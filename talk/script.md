# Your Tool Is in Another Castle

**MCP Community Connect SF · 28-minute main stage run**

Language rule: report mechanisms, versions, and named boundaries. Do not score
frameworks, infer maintainer intent, or claim equivalent model-input capture.

Run `npm run talk:present`, then click **Open audience**. Navigate from the
presenter console; its current slide, next slide, full script, timer, and clean
audience window stay synchronized.

The HTML deck opens with 23 main slides. In its standalone mode, press `A` to
include appendix slides, `N` for short presenter notes, `T` for the timer, or
`P` to open the presenter console.

The opening five slides rebuild the shape of Nate Barbettini's "MCP in plain
English" explanation on purpose, using my own examples rather than his. The talk
then tests the one piece that explanation leaves standing. The article is cited
on slide 2 and quoted on slide 6; credit him out loud at both.

## 1 · Title | 0:00

Hi, I’m Thierry.

MCP promises that I can build a tool once and connect it to many clients.

I wanted to test the next question: after an agent framework adapts that tool,
does the same representation exist on the other side?

So I built one test server, used one shared MCP revision, passed its definitions
and results through five framework integrations, and recorded what changed.

To explain why that question matters, I am going to borrow the best explanation
of MCP I know, and then go one step past where it stops.

## 2 · The intern in the strange office | 0:40

Imagine you hire a brilliant intern.

Great writer, great education, enormous amount of knowledge in their head. One
catch: they work in a windowless room. No internet, no phone, no library.

The only thing that fits under the door is a sheet of paper.

You slide a note in. They read it, write a reply, and slide it back out.

That is a language model. It reads text and writes text. Everything it knows
about your particular problem, somebody wrote down and passed to it.

The analogy is Nate Barbettini’s, from a post called “Model Context Protocol in
plain English.” It is the clearest explanation of MCP I know and it is on the
slide. My examples from here are my own, so if you want his, go read the post.

Now a customer writes in asking where their order is. The intern cannot help.
Your order database is not in the room, and it is certainly not in their head.

## 3 · The workaround | 1:25

So you find a workaround.

You cannot pass the order database under the door, but you can pass
instructions for asking it something.

You write: if you need the order system, write `LOOKUP(order_id)`.

The intern writes back `LOOKUP(4417)`.

You run the real query on your side and slide the answer back: shipped the
eleventh, arriving the sixteenth, carrier DHL.

Now the intern can write the customer a real answer.

Notice the answer is a small record, not a single number. Results have shape.
Hold on to that, because the shape is what the rest of the talk is about.

That exchange is the whole pattern. You describe what is available, the model
requests it, your application code executes it, and you hand the result back.
That is tool calling. Run it in a loop and people call it an agent.

## 4 · More tools, more glue | 2:15

Once that works, you do not stop at order lookups.

Searching your docs. Reading a calendar. Sending email. Refunding a payment.

Every single one needs the same two pieces of code from you: a description the
model can read, and code that performs the real call and hands the result back.

Five tools, five pieces of glue. Fifty tools, fifty pieces of glue. And the
weather company is writing their own version of the same glue, for their own
customers, at the same time.

At some point the cranky engineer in the back of your head starts shouting
about repeating yourself.

## 5 · MCP is a standard interface | 2:55

MCP is the agreement that stops the repetition.

Your application gets an MCP client. Any MCP server it connects to lists its
tools and accepts calls through the same interface. Write the integration once,
reuse it in any MCP client.

That is the promise, and it is intentionally boring. It is standardization, not
AI magic.

Everything in the rest of this talk is a test of that promise.

## 6 · The part that stayed the same | 3:40

Here is the sentence from Nate’s post that this talk is built on:

“The model still only sees the `get_weather` tool. The MCP conversation happens
between the application and the MCP server.”

His running example is a weather tool and mine was an order lookup. The point
is identical either way.

That is exactly right, and it is the whole opening.

From the model’s point of view, nothing changed. It still sits in the windowless
room. It still only ever reads a note somebody else wrote.

MCP standardized everything below the client. It did not standardize the note.

Somebody still writes the note. In an agent application, that somebody is your
framework.

So I went and read the note.

## 7 · One source result | 4:35

Let’s start with what the server sends.

This is one valid `CallToolResult` from one MCP server on MCP 2025-11-25. In a
single response it contains text, an image, audio, an embedded resource, a
resource link, and machine-readable structured JSON.

Each source field contains a different test-only marker, URI, or MIME type.
Think of the markers as different colors of tracer dye: after adaptation, we can
search for each one and see exactly where it landed.

Every integration receives this same source result.

## 8 · Five boundary objects | 5:30

Here is the note each framework wrote.

Be clear about what this slide is. The MCP response was identical in all five
runs. Nothing on the server changed. The row at the top is that one response.
The five cards below are what each framework handed back afterward, at the
integration API named on the card.

At CrewAI’s direct tool-return boundary, the content becomes a Python-list-shaped
string.

LangChain receives the result, but its measured conversion raises when it
reaches the audio block.

OpenAI Agents keeps text and image while serializing the other content blocks
into text.

Pydantic AI keeps text, image, and audio while reducing the resource forms to
text.

Mastra exposes the structured value at this boundary while omitting the
accompanying content blocks.

These are what I saw, at the exact package versions I ran, at the exact function
named on each card. They are not five equivalent final payloads to the model. I
did not follow the object that far.

One server. One invocation. One valid MCP result. Five different
framework-native representations.

## 9 · The interoperability gap | 7:15

That is the talk:

The connection was portable. The agent-facing contract was not.

Go back to the glue for a second. The reason MCP exists is that everybody was
writing the same integration code over and over. MCP removed that duplication
below the client.

It did not remove it above the client. The code that turns an MCP result into
something an agent runtime can use is still written once per framework. There
are five of them here, and they do not agree.

So “supports MCP” answers the connectivity question. It does not tell an
application whether it will receive typed JSON, serialized text, a framework
message, an exception, or some combination of them.

Two different questions hide inside “does it support MCP.” The first one is: can
these two programs talk to each other? That one is solved, and MCP solved it.
The second one is: once they have finished talking, do I get the same thing to
work with? That one is not solved, and nothing in the protocol promises it.

The names for those on the slide are protocol connectivity and contract
portability.

There is already a known gap between “the server implements MCP” and “real
clients can use it.” This study asks the next question: after the client
successfully receives the MCP object, what contract does the framework expose?

## 10 · A tool-execution error | 8:25

Now reduce the experiment to one boolean.

The test server has a `delete_account` tool. If confirmation is missing, it
returns the text “confirm was not set” and sets `isError` to true.

The deletion does not run.

This is not a malformed request. It is a valid MCP response reporting that the
requested tool operation failed.

## 11 · Two outcome layers | 9:20

JSON-RPC and MCP report two different outcomes.

JSON-RPC returns `result`. That means the `tools/call` request was recognized
and processed. An unknown method or malformed request would instead produce a
JSON-RPC protocol error.

That outer wrapper is sometimes called the envelope. It carries the protocol
version, the request ID, and either a result or a protocol error.

Nested inside that valid result is the MCP object, a `CallToolResult`. It has a
`content` array, which holds the prose, and sitting right beside it a boolean
field called `isError`. Here it is true.

That field is the whole subject of the next few slides, so let me be exact about
it. It is a boolean on the result object, and it is the only field MCP defines
to mark a result as a tool execution error. The protocol exchange worked; the
requested operation did not.

The specification gives that inner case a name. It is a tool execution error,
and it is a deliberate category: actionable feedback a model can use to
self-correct and retry with adjusted parameters. Unknown tool or malformed
arguments are the other category, and those are protocol errors.

So an adapter now has to express that named category in the framework’s own
execution model.

## 12 · Audience prediction | 10:40

Now imagine you are writing the adapter. You are the one writing the note.

The server says the requested operation failed.

What would you hand the agent?

Would it be a value, a message, an exception, or something else?

There is no protocol-mandated framework answer. Let’s see what the pinned
integrations expose.

## 13 · Error-result reveal | 11:40

At these pinned boundaries, that one boolean becomes three contracts. The color
of each card is the contract family, not a score.

The first three are the same contract: a plain result.

CrewAI’s `BaseTool.run` returns ordinary result text.

LangChain’s direct `StructuredTool.ainvoke` returns an ordinary text block.

OpenAI Agents’ `MCPUtil.invoke_mcp_tool` returns a normal `ToolOutput`.

At those three captures, the `isError` flag is no longer present.

Pydantic AI’s `MCPToolset.direct_call_tool` raises `ModelRetry`.

Mastra’s tool-action execution throws an error.

No measured row returns the unchanged MCP `CallToolResult`.

These claims match the published 2025-11-25 dataset and the live demo exactly.
They do not claim that a later tool node, event stream, or provider request
exposes the same object.

## 14 · What the flag was for | 13:30

So what? Why does a missing boolean matter when the sentence “confirm was not
set” is still sitting right there?

Start with what the specification actually asks for. A tool execution error is
defined as actionable feedback a model can use to self-correct, and the spec
puts a normative requirement on clients: clients SHOULD provide tool execution
errors to language models to enable self-correction.

Be precise about what we measured, because this cuts both ways.

The explanatory text survived in every captured path. So the part that reaches
the model, the prose, is largely intact. I am not claiming the model is blind to
the failure, and this study did not measure model behavior at all.

What did not survive is the marking. In three of five captures there is no
typed field that says “this one is the error case.” The result is shaped exactly
like a success.

Now take one ordinary question an application asks: did this tool call fail?

Against the raw MCP result that is one line. You read `isError`.

After adaptation it is three different implementations. In the plain-result
contracts there is no typed field to read at all, so the only signal is prose,
and matching on prose is not a contract. In Pydantic AI you catch `ModelRetry`.
In Mastra you catch a thrown error.

That is the practical cost. Anything that branches on failure, a retry policy, a
failure counter, a circuit breaker, an audit log, a confirmation gate, has to be
written against the adapter rather than against MCP. And the one you write for
one framework does not carry to the next.

## 15 · Does it matter? Four teams already answered | 14:45

You do not have to take my word for any of that, and I would rather you did not.

These are four merged pull requests from four independent maintainer teams, and
I am showing you their commit titles verbatim.

March: the Claude Agent SDK merges “propagate `is_error` flag from SDK MCP tool
results.”

June: LangChain merges “surface MCP tool execution errors as failed tool
output.”

July: Mastra merges, and read this one carefully, “honor `isError` on
`CallToolResult` so failed MCP tool calls aren’t recorded as successes.”

That is a maintainer stating the consequence in a commit title. Failed calls
were being recorded as successes.

August: OpenAI Agents merges “keep MCP error content when structured output is
enabled.” In that one it was not only the flag; under a particular
configuration the error content itself was dropped.

Two fair points about this slide.

First, this problem clearly predates my project. I am not claiming discovery.
The contribution here is a shared fixture and a versioned cross-framework
comparison, not the observation that error handling is tricky.

Second, and this is the actual finding: every one of those fixes lands at a
boundary that team chose. Different layer, different object, different release.
Which is exactly the point. Where the failure signal lives is a per-framework
decision, not something the protocol guarantees you.

## 16 · Method | 15:45

Quickly, how this was actually done, because the method is the whole argument.

Everything runs on MCP 2025-11-25, for the boring reason that all five
frameworks speak that version. One test server sends every framework the same
deliberately awkward tools and results. Every field in them carries its own
marker, the tracer dye, so I can go looking for it afterward.

The important bullet is the third one, so let me say what it means.

I did not write my own version of what I think each framework does to an MCP
result. I called the framework’s own conversion function, the one it ships and
uses in production, and I looked at what it handed back. Those are the function
names printed on every card: `BaseTool.run`, `StructuredTool.ainvoke`,
`MCPUtil.invoke_mcp_tool`, `MCPToolset.direct_call_tool`, and Mastra’s tool
action. If I had hand-rolled the conversion, these results would measure my
guess instead of the framework.

The last bullet is the honest limit. “What reaches the agent” sounds like one
place, but a framework has several: a tool return, a message, an exception, an
event, a request to the provider, the final model input. I read one object per
framework, and I stop there. I do not follow it all the way to the model.

That is why every published result is stamped with the exact function I called
and the exact object it returned. In this project that stamp is called the
capture boundary, and a claim without one is not worth much.

Where I do not know, the site says unknown. Nothing gets inferred into a pass or
a fail.

## 17 · Live MCP demo | 16:50

The measurements are also available through mcp-mirror itself.

mcp-mirror runs as a read-only MCP server. I can submit the tool definition or
result we just saw and ask which protocol features it uses and what the
published framework observations say.

Which should we inspect first: the definition or the result?

The demo invokes the real inspection tools and returns versioned evidence. It
does not execute the submitted tool and does not call a model.

## 18 · Tool annotations | 19:25

The same translation question appears before invocation.

The server marks `delete_account` with `destructiveHint: true`.

We send the same `Tool` through each integration and locate that exact boolean
after adaptation.

In the versions I ran, LangChain and Pydantic AI keep it, but off to the side in
framework metadata, not in the part of the tool definition that gets sent to the
model. The other three adapted tool objects do not carry that hint on the same
path at all.

Annotations are advisory, not authorization. The point is narrower than it
sounds: if your code only reads what gets sent to the model, it cannot see a
field that is sitting somewhere else, or that is not there at all.

So if a policy depends on annotations, it must read a verified application-layer
representation that contains them. Authorization and confirmation stay
independently enforced.

## 19 · Structured-content destinations | 21:10

The opening result also carried two channels:

`content[]` contains unstructured blocks such as text, images, audio, and
resources.

`structuredContent` contains machine-readable JSON.

After adaptation, current framework paths can place that JSON in an artifact,
use it as framework output, expose it as model-visible JSON when configured, or
fall back to text-oriented output.

This is the same shape of problem as the error flag: it decides whether
application code can validate and consume a value as data rather than reparsing
prose.

The third column matters. Three of these rows are what our run captured. Two are
the documented behavior of a path this study did not capture directly.

Again, these are different destinations, not a support ladder.

## 20 · Interpretation | 22:55

The framework names remain in the talk because the observations would be
unverifiable without them.

But this is not an overall ranking:

- Each framework exposes a different abstraction.
- Some transformations are intentional.
- Some are configurable.
- Some have changed between releases, including the four fixes we just saw.
- A changed field is not automatically a bug.

The operational question is whether server authors and application developers
know which contract exists after conversion.

## 21 · What about the other protocols | 23:55

A fair question here: isn’t the ecosystem already fixing this?

Three things usually come up. MCP standardizes application to server. A2A
standardizes agent to agent. ACP, the editor protocol from Zed and JetBrains,
standardizes editor to coding agent.

All three are wire protocols. Each one standardizes a boundary between two
processes.

The boundary I measured is inside a single process, between the adapter and the
runtime’s own objects. A wire protocol does not reach in there, because that is
a library API decision, not a message format.

A2A says so itself. Quoting: “A2A does not specify how an agent talks to its own
sub-agents or how it invokes tools.” Its guidance instead is to use your
framework’s native primitives.

That last phrase is this whole talk.

## 22 · What developers can do | 24:35

There are five practical steps:

First, test the framework-native object, not only the source server response.

Second, include execution errors, structured data, and mixed content in
integration fixtures.

Third, keep a useful textual failure explanation alongside `isError`, because at
several boundaries the text is the part that survives.

Fourth, read safety metadata from a verified application layer rather than an
assumed schema.

Fifth, pin the framework adapter and MCP SDK versions covered by the test.

Protocol conformance and boundary fidelity are complementary. One checks the
exchange; the other checks the representation after it.

## 23 · Close | 26:35

We started with an intern in a windowless room who can only read notes somebody
else wrote.

MCP standardized how we fetch what goes into that note. It did not standardize
the note.

So do not ask only:

“What did the server send?”

Also ask:

“At which boundary, in which representation, did it arrive?”

The tool can be in every castle. Check what survived the journey.

Thank you.

---

## Appendix controls

Press `A` in the HTML deck to include the appendix slides. They contain:

- The agent-loop diagram.
- The complete tool declaration.
- The JSON-RPC wire shape beside framework-native types.
- The abstract source-level code comparison.
- The source-language analogy.
- The missing-contract formulation.
- The full adapter path.
- The capture-boundary rigor slide.
- Structured-content definitions and test mechanics.
- Rich-content fixture details and the complete five-row observation table.
- Study limitations.
- Protocol conformance comparison.
- Published coverage counts.

## Sources for claims made on stage

- Nate Barbettini, “Model Context Protocol in plain English,” 9 September 2026.
  Source of the intern analogy, the note-under-the-door mechanic, the glue-code
  motivation, and the quotation on slide 6. The worked examples in slides 3 and
  4 are mine, not his:
  <https://caffeinate.blog/post/mcp-in-plain-english/>
- Nate Barbettini, “Introducing the MCP Debugger”:
  <https://caffeinate.blog/post/introducing-mcp-debugger/>
- MCP tool error semantics, including the tool-execution-error definition and
  the client SHOULD quoted on slide 14:
  <https://modelcontextprotocol.io/specification/2026-07-28/server/tools#error-handling>
- Official MCP conformance:
  <https://github.com/modelcontextprotocol/conformance>
- A2A Protocol specification, “What A2A is not,” quoted on slide 21. The
  sentence on the slide and the phrase “use your framework’s native primitives”
  are both verbatim; the slide elides only the dash between them. A2A reached
  v1.0 in 2026 and is hosted by the Linux Foundation:
  <https://a2a-protocol.org/latest/>
- Agent Client Protocol, the Zed and JetBrains editor protocol referenced on
  slide 21. Stable protocol version 1:
  <https://agentclientprotocol.com/>

Slide 15 quotes these four merged pull-request titles verbatim. Re-verify before
the talk with `gh pr view <url> --json title,state,mergedAt`.

- Claude Agent SDK, merged 25 March 2026, “fix: propagate is_error flag from SDK
  MCP tool results”:
  <https://github.com/anthropics/claude-agent-sdk-python/pull/717>
- LangChain, merged 10 June 2026, “feat: surface MCP tool execution errors as
  failed tool output”:
  <https://github.com/langchain-ai/langchain-mcp-adapters/pull/540>
- Mastra, merged 1 July 2026, “fix(mcp): honor isError on CallToolResult so
  failed MCP tool calls aren’t recorded as successes”:
  <https://github.com/mastra-ai/mastra/pull/18482>
- OpenAI Agents, merged 5 August 2026, “fix(mcp): keep MCP error content when
  structured output is enabled”:
  <https://github.com/openai/openai-agents-python/pull/4224>

Adjacent work:

- LangChain structured-content report:
  <https://github.com/langchain-ai/langchain-mcp-adapters/issues/283>
- Microsoft Agent Framework structured-content report:
  <https://github.com/microsoft/agent-framework/issues/3313>
- LLM-Rosetta translation-fidelity paper:
  <https://arxiv.org/abs/2604.09360>
- MCPBench:
  <https://github.com/unimcp/mcpbench>
- MCPEval:
  <https://arxiv.org/abs/2507.12806>
- MCP-AgentBench:
  <https://doi.org/10.1609/aaai.v40i37.40347>

## Answers to likely questions

**Are you saying frameworks lose the error?**

At the pinned result boundaries, CrewAI, LangChain, and OpenAI Agents retain the
explanatory text but not the flag. Pydantic AI and Mastra preserve failure
meaning as control flow. Other later framework paths may expose additional
metadata; every claim in the talk is scoped to its named capture.

**If the text survives, does the missing flag actually hurt anything?**

It changes who can act on the failure. The prose is for the model, and the model
still gets it. The boolean is for your code, and at three captures there is no
boolean, so a retry policy, failure counter, circuit breaker, audit log, or
confirmation gate has nothing typed to branch on. Mastra’s own merged fix states
that consequence directly: without honoring `isError`, failed calls were
recorded as successes.

**Aren’t those four fixes proof the frameworks already solved this?**

They are proof the issue is real and taken seriously. They are not proof of a
shared contract, because each fix lands at a boundary that team selected, at a
different layer, in a different release. Our captures are at the direct
tool-return API named on each card, which in some cases sits earlier in the path
than where a given fix applies. That is stated on the reveal slide.

**Which representation is best?**

That depends on the framework’s execution model. The talk does not score them.
It argues that applications must test the representation they actually use.

**Did you capture the exact model payload?**

Not consistently across all five. The project captures declared deterministic
framework boundaries. Equivalent provider-request or model-input capture is
future work.

**Are you first?**

No priority claim. Individual framework issues, MCP benchmarks, and API
translation research already cover adjacent or overlapping problems. The
project’s contribution is a shared cross-framework fixture and explicit,
versioned boundary comparison.

**Isn’t the opening just Nate’s blog post?**

The first five slides deliberately rebuild the shape of his explanation,
credited on the slides and out loud, because it is the clearest public framing
of why MCP exists. The worked examples are different on purpose: his are a
calculator and a weather lookup, mine are an order lookup and a set of
business tools. The talk then begins where that post ends. His own line is that
the model still only sees the tool the application prepared, and this is a
measurement of what five applications actually prepared from identical input.

## Delivery

- Target 27 to 28 minutes, leaving two minutes for questions.
- The build-up is five slides and roughly four minutes. It earns the reveal; do
  not let it sprawl.
- Let the five-way result sit before explaining it.
- Slides 14 and 15 are the answer to “so what.” Do not rush them, and do not
  editorialize past the commit titles.
- Keep the live demo under three minutes.
- The numbered sections are spoken words only, safe to read raw. Every stage
  direction lives here instead.
- Pause after the last line of slides 6 and 8 before advancing.
- Slide 12 is the second interaction. Stop talking after the question and take
  two or three shouted answers. Do not show choices.
- Slide 17 demo command: `uv run python scripts/demo_mcp_server.py --first
  result`, or `--first definition`. Take the louder answer from the room. If the
  terminal misbehaves, jump back to the five-boundary-objects slide and do not
  debug on stage.
- Timing gates: first data by 5:30, thesis by 7:30, significance by 15:45,
  demo by 16:50, recommendations by 24:35.
- Slide 21 is the cheapest cut if you are behind. Drop the slide and say one
  sentence from the lectern: A2A and ACP standardize other boundaries between
  processes, and this one is inside a process, so neither reaches it.
- If more than a minute behind at slide 5, cut slides 3 and 4 to one sentence
  each: you pass instructions for asking, and then you write that glue once per
  integration.
- If more than two minutes behind later, skip slide 19 and state its conclusion
  in one sentence: structured JSON also lands in framework-specific
  destinations.
- Never describe the site’s support codes as framework scores.
- Prefer “maps,” “converts,” “retains,” “omits,” and “at this boundary.”
