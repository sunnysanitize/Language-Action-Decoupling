  6. Implement the remaining agents.
     boss.py and kengriffin.py are empty, memory.py is only a plan, and
     trader.py is still a simple scripted trader. Finish each agent and add
     tests for its behavior.

  7. Connect all agents to the episode.
     The episode currently runs only two trader policies. Add the boss and
     other planned roles, then give each agent the correct private memory and
     information between rounds.

  8. Record and replay every model call so an episode can be re-run exactly.
     Put the prompts, responses, model, and sampling settings in the run data.

  9. Build the four detector datasets.
     Build the situation, observable, private-chat, and private-reasoning
     datasets for withholding and misreporting.

  10. Run a small pilot.
      Make sure the agents, labels, saved data, and detectors work together.

  11. Run the full experiment.
