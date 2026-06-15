# Hermes integration

Hermes agents claim a callsign at boot the same way Claude Code does, but through the Python API instead of a shell hook.

## Minimum agent change

```python
# at the very top of your agent's main loop
from callsign.hermes import HermesCallsign

cs = HermesCallsign.boot(
    agent_id="lead",            # logical agent role
    project_path=os.getcwd(),    # used for project-stable name reuse
)

# 1) introduce yourself
print(cs.banner())

# 2) inject the callsign context into the model's system prompt
system_prompt = system_prompt + "\n\n" + cs.context_block()

# 3) replace your iMessage send with the wrapper
cs.send_imessage("starting wellrx scheduled run.")
```

## Routing inbound iMessages to the right Hermes agent

If your Hermes orchestrator already subscribes to the iMessage stream, plug `callsign.router` in:

```python
from callsign import router

for raw in imsg_stream:
    hit = router.route(raw.text)
    if hit:
        dispatch_to_agent(hit.session.session_uid, hit.body)
    else:
        dispatch_to_lead(raw.text)   # legacy "Brodie," default
```

## Cron jobs

For unattended cron-triggered Hermes agents, set `HERMES_SESSION_ID` to the job ID so reruns reuse the same callsign:

```bash
HERMES_SESSION_ID=wellrx-nightly-2026-06-15 \
    python -m hermes.jobs.wellrx_nightly
```

## Shared registry

Claude Code and Hermes both write to `~/.callsign/registry.db`. A name claimed by one platform is unavailable to the other until the session retires, so you never get two agents both called `Frank` at the same time.
