# {{project_name}} Plan

> Run `sago plan` to generate this file from your PROJECT.md and REQUIREMENTS.md.

## Task Schema

Each task uses this XML structure:

```
<phases>
  <dependencies>
    <package>package-name>=version</package>
  </dependencies>

  <review>
    Review the completed phase. For every issue:
    - Describe the problem with file and line references
    - Assess severity (critical, warning, suggestion)
    - Provide concrete fix instructions
    Focus on: code quality, edge cases, DRY violations,
    security issues, and alignment with requirements.
  </review>

  <phase name="Phase 1: Name">
    <description>What this phase accomplishes</description>
    <task id="1.1">
      <name>Descriptive task name</name>
      <files>src/file.py</files>
      <action>Detailed instructions for what to implement</action>
      <verify>command that exits 0 on success</verify>
      <done>What "done" looks like</done>
    </task>
    <task id="1.2" depends_on="1.1">
      <name>Another task that depends on 1.1</name>
      <files>src/other.py</files>
      <action>Detailed instructions</action>
      <verify>command that exits 0 on success</verify>
      <done>What "done" looks like</done>
    </task>
  </phase>
</phases>
```

## Execution Rules

1. **Follow task dependencies** -- check `depends_on` to determine task order. Tasks without `depends_on` depend on all prior tasks in their phase.
2. **Verify before proceeding** -- each task must pass its verify command
3. **Atomic commits** -- one commit per completed task (with `--git-commit`)
