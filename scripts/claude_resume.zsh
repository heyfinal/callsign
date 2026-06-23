# Callsign-aware `claude` wrapper — resume a session by its agent name.
#   claude --resume ROOK     →  resolves ROOK -> session_id -> native resume
# Falls through untouched for real session-ids, the interactive picker, and all
# other invocations. Sourced from ~/.zshrc.
claude() {
  emulate -L zsh
  local -a a; a=("$@")
  local i n sid
  for (( i = 1; i <= ${#a}; i++ )); do
    if [[ "${a[i]}" == "--resume" || "${a[i]}" == "-r" ]]; then
      n="${a[i+1]}"
      # only rewrite when the value looks like a NAME (not a flag, not a uuid)
      if [[ -n "$n" && "$n" != -* && ! "$n" =~ '^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-' ]]; then
        sid="$(python3 "$HOME/.claude/scripts/project_callsign.py" resume-id "$n" 2>/dev/null)"
        [[ -n "$sid" ]] && a[i+1]="$sid"
      fi
      break
    fi
  done
  command claude "${a[@]}"
}
