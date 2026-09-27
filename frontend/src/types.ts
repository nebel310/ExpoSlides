export type Box = { x: number; y: number; width: number; height: number };
export type Dataset = {
  id: string; name: string; columns: string[]; rows: (string | number)[][];
  source: string; unit: string;
};
export type Visual = {
  kind: "table" | "bar" | "line" | "pie" | "process" | "comparison" | "smartart" | "icon";
  dataset_id?: string | null; labels: string[];
  icon?: "arrow" | "check" | "info"; source_shape_id?: number | null;
};
export type StorySlide = {
  id: string; title: string; paragraphs: string[]; source_ids: string[];
  visual: Visual | null; notes: string;
};
export type Story = { schema_version: "1.0"; title: string; slides: StorySlide[] };
export type DesignRequest = {
  script: string; purpose: string; audience: string; slide_count: number;
  count_mode: "exact" | "maximum"; language: string; mode: "llm" | "extractive";
  required_messages: string[]; datasets: Dataset[];
  contextual_audit: boolean;
  generated_image?: {
    enabled: boolean; prompt: string; seed: number; width: number; height: number;
    source_ids: string[]; palette: string[]; slide_id?: string | null;
  };
};
export type Pattern = {
  name: string; source_slide_index: number; font: string; palette: string[]; warnings: string[];
  visual_shape_ids?: Record<string, number[]>;
};
export type Profile = { width: number; height: number; patterns: Pattern[]; warnings: string[] };
export type Template = { id: string; name: string; profile?: Profile; slide_count?: number };
export type Issue = {
  id: string; message: string; severity: "error" | "warning" | "info";
  slide_index?: number; slide_id: string; rule_id?: string; rule: string;
  bbox?: Box | null; box?: { left: number; top: number; width: number; height: number } | null;
  fix_available?: boolean; fix: string; evidence?: string; check_type: string;
};
export type Variant = {
  id: string; name: string; description: string; revision: number; issues: Issue[];
  preview_urls: string[]; exports: Partial<Record<"pptx" | "pdf" | "html", string>>;
  limitations?: string[]; contextual_status?: string;
  audit?: { limitations: string[]; contextual_status: string; checks?: string[] };
};
export type Job = {
  id: string; status: string; stage?: string; error?: string | null;
  created_at?: number;
  template_id?: string;
  story?: Story; profile?: Profile; variants?: Variant[]; warnings?: string[];
  request?: DesignRequest; template?: Template;
};
