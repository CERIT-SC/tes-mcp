{{/*
Resolve the externally-visible hostname.
- FQDN (contains a dot) → used as-is.
- Short host → <host>.<namespace>.dyn.cloud.e-infra.cz
*/}}
{{- define "tes-mcp.host" -}}
{{- if contains "." .Values.host -}}
{{- .Values.host -}}
{{- else -}}
{{- printf "%s.%s.dyn.cloud.e-infra.cz" .Values.host .Release.Namespace -}}
{{- end -}}
{{- end -}}

{{/*
Common labels.
*/}}
{{- define "tes-mcp.labels" -}}
app.kubernetes.io/name: {{ .Chart.Name }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end -}}

{{/*
Selectors (immutable, minimal).
*/}}
{{- define "tes-mcp.selectorLabels" -}}
app.kubernetes.io/name: {{ .Chart.Name }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end -}}

{{/*
Full resource name.
*/}}
{{- define "tes-mcp.fullname" -}}
{{- .Values.fullnameOverride | default (printf "%s-%s" .Release.Name .Chart.Name) | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{/*
Container image reference.
*/}}
{{- define "tes-mcp.image" -}}
{{- if .Values.image.digest -}}
{{- printf "%s@%s" .Values.image.repository .Values.image.digest -}}
{{- else -}}
{{- printf "%s:%s" .Values.image.repository .Values.image.tag -}}
{{- end -}}
{{- end -}}
