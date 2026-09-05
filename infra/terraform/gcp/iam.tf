resource "google_project_iam_member" "aiplatform_user" {
  project = google_project.this.project_id
  role    = "roles/aiplatform.user"
  member  = "user:${var.adc_email}"
}
