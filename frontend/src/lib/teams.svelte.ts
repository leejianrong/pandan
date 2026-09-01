// Team state as Svelte 5 runes (M9 V70, KAN-1059; ADR 0021).
// Teams are user-scoped (not board-scoped), so — like tokens — the team LIST
// loads once at login (board.svelte.ts's onMount, alongside boards/epics), not
// lazily per-view: the BoardSwitcher's Team picker needs it too. A team's
// MEMBERS are scoped to whichever team is currently open in TeamModal, mirroring
// members.svelte.ts's board-scoped shape. Server state is authoritative — every
// mutation refetches, matching the rest of the app's no-optimistic-UI convention.

import {
  addTeamMember,
  createTeam,
  deleteTeam,
  listTeamMembers,
  listTeams,
  removeTeamMember,
  updateTeam,
  updateTeamMember,
  type Role,
  type Team,
  type TeamMember,
} from "./api";

export const teamStore = $state<{
  teams: Team[];
  loading: boolean;
  error: string | null;
}>({ teams: [], loading: false, error: null });

export async function refetchTeams(): Promise<void> {
  teamStore.loading = true;
  teamStore.error = null;
  try {
    teamStore.teams = await listTeams();
  } catch (e) {
    teamStore.error = e instanceof Error ? e.message : "Failed to load teams";
  } finally {
    teamStore.loading = false;
  }
}

export async function addTeam(name: string): Promise<void> {
  await createTeam({ name });
  await refetchTeams();
}

export async function editTeam(id: number, name: string): Promise<void> {
  await updateTeam(id, { name });
  await refetchTeams();
}

export async function removeTeam(id: number): Promise<void> {
  await deleteTeam(id);
  await refetchTeams();
}

// The team currently open in TeamModal — its members, loaded on demand.
export const teamMemberStore = $state<{
  teamId: number | null;
  members: TeamMember[];
  loading: boolean;
  error: string | null;
}>({ teamId: null, members: [], loading: false, error: null });

export async function refetchTeamMembers(teamId: number): Promise<void> {
  teamMemberStore.teamId = teamId;
  teamMemberStore.loading = true;
  teamMemberStore.error = null;
  try {
    teamMemberStore.members = await listTeamMembers(teamId);
  } catch (e) {
    teamMemberStore.error = e instanceof Error ? e.message : "Failed to load members";
  } finally {
    teamMemberStore.loading = false;
  }
}

export async function inviteTeamMember(
  teamId: number,
  email: string,
  role: Role,
): Promise<void> {
  await addTeamMember(teamId, { email, role });
  await refetchTeamMembers(teamId);
}

export async function changeTeamMemberRole(
  teamId: number,
  memberId: number,
  role: Role,
): Promise<void> {
  await updateTeamMember(teamId, memberId, { role });
  await refetchTeamMembers(teamId);
}

export async function kickTeamMember(teamId: number, memberId: number): Promise<void> {
  await removeTeamMember(teamId, memberId);
  await refetchTeamMembers(teamId);
}
