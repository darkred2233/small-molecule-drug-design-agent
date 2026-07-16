def test_legacy_generator_agent_imports():
    from medagent.agents.generator import GenerationStrategy, GeneratorAgent

    assert GeneratorAgent.__name__ == "GeneratorAgent"
    assert GenerationStrategy(method="reinvent4", seed_ligands=["CCO"], target_count=1, constraints={})
