"""Read-only results explorer for recorded SDPLab benchmark runs.

Only ``sdplab.dashboard.app`` imports Streamlit; ``discovery``, ``data`` and ``charts`` are plain
Python (pandas/Altair for frames and charts) so they can be tested without a running server. The
dashboard never runs a benchmark and only reads files from the results directory.
"""
