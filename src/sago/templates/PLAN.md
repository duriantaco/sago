# {{project_name}} Plan

> Run `sago plan` to generate this file from your PROJECT.md and REQUIREMENTS.md.

## Task Schema

Each task uses this XML structure:

```xml
<phases>
  <phase name="Phase 1: Name">
    <description>What this phase accomplishes</description>
    <task id="1.1">
      <name>Short task name</name>
      <files>src/file.py</files>
      <action>Detailed instructions for what to implement</action>
      <verify>command that exits 0 on success</verify>
      <done>What "done" looks like</done>
    </task>
  </phase>
</phases>
```

## Execution Rules

1. **Sequential within phases** -- complete tasks in order
2. **Verify before proceeding** -- each task must pass its verify command
3. **Atomic commits** -- one commit per completed task (with `--git-commit`)
