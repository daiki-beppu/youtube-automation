# apply 後も保持し、state 喪失時に同じ取り込み範囲を復元できるようにする。
import {
  to = google_project.this
  id = "projects/${var.project_id}"
}

import {
  to = google_project_service.apis["youtube.googleapis.com"]
  id = "${var.project_id}/youtube.googleapis.com"
}

import {
  to = google_project_service.apis["youtubeanalytics.googleapis.com"]
  id = "${var.project_id}/youtubeanalytics.googleapis.com"
}

import {
  to = google_project_service.apis["youtubereporting.googleapis.com"]
  id = "${var.project_id}/youtubereporting.googleapis.com"
}

import {
  to = google_project_service.apis["aiplatform.googleapis.com"]
  id = "${var.project_id}/aiplatform.googleapis.com"
}

import {
  to = google_project_service.apis["generativelanguage.googleapis.com"]
  id = "${var.project_id}/generativelanguage.googleapis.com"
}

import {
  to = google_project_service.apis["storage.googleapis.com"]
  id = "${var.project_id}/storage.googleapis.com"
}

import {
  to = google_project_iam_member.aiplatform_user
  id = "${var.project_id} roles/aiplatform.user user:${var.adc_email}"
}
