// Workspace state as Svelte 5 runes (M9 V70, KAN-1059; ADR 0021).
// Workspaces are user-scoped (not board-scoped), so — like tokens — the workspace LIST
// loads once at login (board.svelte.ts's onMount, alongside boards/epics), not
// lazily per-view: the BoardSwitcher's Workspace picker needs it too. A workspace's
// MEMBERS are scoped to whichever workspace is currently open in WorkspaceModal, mirroring
// members.svelte.ts's board-scoped shape. Server state is authoritative — every
// mutation refetches, matching the rest of the app's no-optimistic-UI convention.

import {
  addWorkspaceMember,
  createWorkspace,
  deleteWorkspace,
  listWorkspaceMembers,
  listWorkspaces,
  removeWorkspaceMember,
  updateWorkspace,
  updateWorkspaceMember,
  type Role,
  type Workspace,
  type WorkspaceMember,
} from "./api";

export const workspaceStore = $state<{
  workspaces: Workspace[];
  loading: boolean;
  error: string | null;
}>({ workspaces: [], loading: false, error: null });

export async function refetchWorkspaces(): Promise<void> {
  workspaceStore.loading = true;
  workspaceStore.error = null;
  try {
    workspaceStore.workspaces = await listWorkspaces();
  } catch (e) {
    workspaceStore.error = e instanceof Error ? e.message : "Failed to load workspaces";
  } finally {
    workspaceStore.loading = false;
  }
}

export async function addWorkspace(name: string): Promise<void> {
  await createWorkspace({ name });
  await refetchWorkspaces();
}

export async function editWorkspace(id: number, name: string): Promise<void> {
  await updateWorkspace(id, { name });
  await refetchWorkspaces();
}

export async function removeWorkspace(id: number): Promise<void> {
  await deleteWorkspace(id);
  await refetchWorkspaces();
}

// The workspace currently open in WorkspaceModal — its members, loaded on demand.
export const workspaceMemberStore = $state<{
  workspaceId: number | null;
  members: WorkspaceMember[];
  loading: boolean;
  error: string | null;
}>({ workspaceId: null, members: [], loading: false, error: null });

export async function refetchWorkspaceMembers(workspaceId: number): Promise<void> {
  workspaceMemberStore.workspaceId = workspaceId;
  workspaceMemberStore.loading = true;
  workspaceMemberStore.error = null;
  try {
    workspaceMemberStore.members = await listWorkspaceMembers(workspaceId);
  } catch (e) {
    workspaceMemberStore.error = e instanceof Error ? e.message : "Failed to load members";
  } finally {
    workspaceMemberStore.loading = false;
  }
}

export async function inviteWorkspaceMember(
  workspaceId: number,
  email: string,
  role: Role,
): Promise<void> {
  await addWorkspaceMember(workspaceId, { email, role });
  await refetchWorkspaceMembers(workspaceId);
}

export async function changeWorkspaceMemberRole(
  workspaceId: number,
  memberId: number,
  role: Role,
): Promise<void> {
  await updateWorkspaceMember(workspaceId, memberId, { role });
  await refetchWorkspaceMembers(workspaceId);
}

export async function kickWorkspaceMember(workspaceId: number, memberId: number): Promise<void> {
  await removeWorkspaceMember(workspaceId, memberId);
  await refetchWorkspaceMembers(workspaceId);
}
