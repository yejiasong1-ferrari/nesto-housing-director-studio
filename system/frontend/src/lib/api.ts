/** @deprecated Prefer `@/lib/saasApi` for SaaS landing / progress. */
export {
  createSaasProject as createProject,
  getProjectStatus,
  startSaasGenerate as startProduction,
  type ProjectStatusResponse as ProjectStatus,
} from "./saasApi";
