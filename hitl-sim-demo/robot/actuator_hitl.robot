*** Settings ***
Documentation     HIL acceptance tests for the fin-actuator controller (DUT).
...               Each test runs a closed-loop scenario against the plant
...               simulator with a scheduled fault and asserts the DUT's safety
...               behavior. Mirrors the pytest oracles in plain language.
Library           HitlLibrary

*** Test Cases ***
Nominal Flight Tracks Without Tripping
    [Documentation]    No faults: the controller must track the command and never
    ...                enter safe-state.
    Run Scenario    nominal
    DUT Should Not Reach Safe State

Hard Over Feedback Triggers Fast Safe State
    [Documentation]    A runaway (hard-over) feedback must be caught quickly.
    Run Scenario    hard_over
    DUT Should Reach Safe State
    Safe State Time Should Be Below    0.32

Dead Sensor Triggers Safe State
    Run Scenario    stuck_at
    DUT Should Reach Safe State
    Safe State Time Should Be Below    0.32

Feedback Loss Triggers Safe State On Timeout
    Run Scenario    packet_loss
    DUT Should Reach Safe State
    Safe State Time Should Be Below    0.30
    Dropped Sample Count Should Be Above    0

Sensor Drift Eventually Triggers Safe State
    [Documentation]    Drift is slower to detect than a hard-over — a larger
    ...                deadline is expected and acceptable.
    Run Scenario    sensor_drift
    DUT Should Reach Safe State
    Safe State Time Should Be Below    0.46
