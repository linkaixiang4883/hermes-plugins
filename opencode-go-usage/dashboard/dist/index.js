/* opencode-go-usage — backend-only plugin (no dashboard UI).
 *
 * This inert bundle exists because the dashboard SPA injects every discovered
 * manifest's `entry` script unconditionally; shipping a no-op file keeps the
 * dashboard console clean (no 404) for a plugin that has no UI of its own.
 */
