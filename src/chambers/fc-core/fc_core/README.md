
## Self-tuning (MUSHY-138)

The chamber model (`sim/chamber_model.py:ChamberParams`) is the source of truth for the
humidifier loop. `control_kernel.ProbeScheduler` fires a 150 s duty=1.0 probe into an in-band
chamber that is not in crash recovery every `probe_interval_h`; `scripts/self-tune/fit-probes.py`
grid-searches the dead time and fits F, Q, tau to each probe window from Timescale;
`scripts/self-tune/push-chamber-params.py` derives SIMC PID gains (`sim/simc.py`, preference knob
`pid_simc_tau_c_seconds`) and pushes them to fc1 plus `fc_config.yaml` when the guard passes.
`test_two_twin_convergence.py` is the end-to-end proof in simulation. Enable on fc1 with
`probe_interval_h: 12`; the nightly timer runs dry until `SELF_TUNE_DRY_RUN` is removed from
`scripts/self-tune/mushy-self-tune.service`.
