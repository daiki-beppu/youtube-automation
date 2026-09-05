resource "google_project_service" "drift_resource_manager" {
  project            = google_project.this.project_id
  service            = "cloudresourcemanager.googleapis.com"
  disable_on_destroy = false
}
