"""Small reviewed fixture graph. Topic content, not inferred learner knowledge."""

REST = "https://nba.uth.tmc.edu/neuroscience/m/s1/chapter01.html"
AP = "https://nba.uth.tmc.edu/neuroscience/m/s1/chapter02.html"
SYNAPSE = "https://nba.uth.tmc.edu/neuroscience/m/s1/chapter05.html"
CONCEPTS = [
    dict(
        id="ionic_gradients",
        label="Ionic gradients",
        aliases=["gradient", "pump", "concentration"],
        prerequisites=[],
        resource_url=REST,
    ),
    dict(
        id="selective_permeability",
        label="Selective permeability",
        aliases=["permeability", "leak", "channel"],
        prerequisites=[],
        resource_url=REST,
    ),
    dict(
        id="resting_potential",
        label="Resting potential",
        aliases=["resting", "membrane potential"],
        prerequisites=["ionic_gradients", "selective_permeability"],
        resource_url=REST,
    ),
    dict(
        id="action_potential_phases",
        label="Action-potential phases",
        aliases=["action potential", "depolarization", "repolarization", "sodium", "potassium"],
        prerequisites=["resting_potential"],
        resource_url=AP,
    ),
    dict(
        id="presynaptic_calcium_entry",
        label="Presynaptic calcium entry",
        aliases=["calcium", "presynaptic"],
        prerequisites=["action_potential_phases"],
        resource_url=SYNAPSE,
    ),
    dict(
        id="transmitter_release",
        label="Transmitter release",
        aliases=["transmitter", "synapse", "vesicle", "release"],
        prerequisites=["presynaptic_calcium_entry"],
        resource_url=SYNAPSE,
    ),
]
# Answers and aliases remain backend-only.
CARDS = [
    dict(
        id="ap-depolarization",
        concept_id="action_potential_phases",
        kind="mcq",
        prompt="In a typical neuron, what mainly drives the rapid rising phase?",
        options={"A": "K+ leaves", "B": "Na+ enters"},
        answers=["b", "option b", "sodium", "na+ enters"],
        explanation="Na+ enters during the rapid rising phase. K+ leaving and Na+ channel inactivation contribute to repolarization.",
    ),
    dict(
        id="resting-permeability",
        concept_id="resting_potential",
        kind="blank",
        prompt="At rest, a typical neuron's membrane is more permeable to which ion: K+ or Na+?",
        options={},
        answers=["k+", "k", "potassium", "potassium ions"],
        explanation="Resting potassium permeability strongly influences resting potential. Gradients and permeability work together.",
    ),
    dict(
        id="ap-repolarization",
        concept_id="action_potential_phases",
        kind="mcq",
        prompt="Which movement contributes to repolarization in a typical neuron?",
        options={"A": "K+ leaves", "B": "Na+ enters"},
        answers=["a", "option a", "k+ leaves", "potassium leaves"],
        explanation="K+ leaving contributes to repolarization, alongside inactivation of Na+ channels.",
    ),
    dict(
        id="gradient-maintenance",
        concept_id="ionic_gradients",
        kind="mcq",
        prompt="What does the sodium-potassium pump maintain over time?",
        options={
            "A": "Ion concentration gradients",
            "B": "Each rapid action-potential rising phase",
        },
        answers=["a", "option a", "ion concentration gradients"],
        explanation="The pump maintains concentration gradients over time. Voltage-gated channels produce rapid action-potential phases.",
    ),
    dict(
        id="selective-channels",
        concept_id="selective_permeability",
        kind="mcq",
        prompt="Why can the membrane respond differently to different ions?",
        options={
            "A": "All channels pass every ion equally",
            "B": "Channels have different ion selectivity",
        },
        answers=["b", "option b"],
        explanation="Channel selectivity and availability help determine relative ionic permeability.",
    ),
    dict(
        id="resting-sign",
        concept_id="resting_potential",
        kind="blank",
        prompt="At rest, is the inside of a typical neuron negative or positive relative to outside?",
        options={},
        answers=["negative", "more negative"],
        explanation="The inside is typically negative relative to the outside at rest.",
    ),
    dict(
        id="calcium-trigger",
        concept_id="presynaptic_calcium_entry",
        kind="mcq",
        prompt="Which ion entering the presynaptic terminal triggers evoked transmitter release?",
        options={"A": "Ca2+", "B": "Na+"},
        answers=["a", "option a", "calcium", "ca2+"],
        explanation="Presynaptic Ca2+ entry triggers mechanisms involved in evoked vesicle fusion.",
    ),
    dict(
        id="release-location",
        concept_id="transmitter_release",
        kind="mcq",
        prompt="Where do vesicles release chemical transmitter?",
        options={"A": "Into the synaptic cleft", "B": "Into the neuron's nucleus"},
        answers=["a", "option a"],
        explanation="Vesicles release transmitter into the synaptic cleft, where it can act on postsynaptic receptors.",
    ),
]
