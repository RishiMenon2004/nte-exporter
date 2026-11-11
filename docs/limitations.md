# Limitations

This is a prototype. It supports the four banners listed in the
[README](../README.md#supported-banners).

- Mystery Box history does not expose a rotation ID in each decoded row. The
  exporter deliberately keeps one unsplit history stream and leaves rotation
  grouping to consumers.
- Pages are anchored to the continuous run starting at page 1. If a missed page
  hasn't been recaptured by the time capture ends, every page after it is ignored
  and reported as a warning.
- Unknown rewards still export with a usable `reward_id`, but their display name
  and rank come from the mapping files, so they're missing until the mappings are
  updated.
- Achievement exports contain only the records sent during login. Achievements
  the game doesn't send aren't added from the game data, because a missing one
  could be unstarted, locked, or unavailable. Observed records are either
  `completed` or `in_progress`. Some compound achievements report progress `0`
  while the server tracks hidden checklist progress, so every record without a
  completion time is `in_progress`.
