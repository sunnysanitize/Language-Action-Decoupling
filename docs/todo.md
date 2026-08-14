  6. Implement the remaining agents.
     memory.py and boss.py are done. kengriffin.py is still empty, and
     trader.py is still a simple scripted trader. Finish each and add tests
     for its behavior.

  7. Connect all agents to the episode.
     Traders and the boss are connected, each with visibility-filtered memory
     and feedback between rounds. The overseer still needs connecting: it
     should produce the FirmDirective that agents/boss.py currently holds as
     fixed text per pressure level.

  8. Record and replay every model call so an episode can be re-run exactly.
     Put the prompts, responses, model, and sampling settings in the run data.

  9. Build the four detector datasets.
     Build the situation, observable, private-chat, and private-reasoning
     datasets for withholding and misreporting.

  10. Run a small pilot.
      Make sure the agents, labels, saved data, and detectors work together.

  11. Run the full experiment.
