"""Evaluation: cases, runner, agents and judges.

A package so its modules are imported as eval.cases, eval.run, ... and never clash with
same-named modules elsewhere (agent/run.py, for one). The scripts still run directly:
python eval/run.py, python eval/cases.py.
"""
