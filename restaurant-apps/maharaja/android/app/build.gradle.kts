plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
    id("org.jetbrains.kotlin.plugin.compose")
}

val apiBaseUrl = providers.gradleProperty("BLAKKEN_API_BASE_URL")
    .orElse("http://10.0.2.2:8000/")
    .get()
val restaurantAppId = providers.gradleProperty("MAHARAJA_APP_ID")
    .orElse("REPLACE_WITH_RESTAURANT_APP_ID")
    .get()
val websocketBaseUrl = providers.gradleProperty("BLAKKEN_WS_BASE_URL")
    .orElse("ws://10.0.2.2:8002/")
    .get()
val playIntegrityRequired = providers.gradleProperty("PLAY_INTEGRITY_REQUIRED")
    .map { it.toBooleanStrict() }
    .orElse(true)
    .get()
val playIntegrityCloudProjectNumber = providers.gradleProperty("PLAY_INTEGRITY_CLOUD_PROJECT_NUMBER")
    .orElse("0")
    .get()
val appRegistrationId = providers.gradleProperty("APP_REGISTRATION_ID").orElse("").get()
require(playIntegrityCloudProjectNumber.toLongOrNull() != null) {
    "PLAY_INTEGRITY_CLOUD_PROJECT_NUMBER must be a numeric Google Cloud project number."
}

android {
    namespace = "no.blakken.restaurants.maharaja"
    compileSdk = 35

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    kotlinOptions {
        jvmTarget = "17"
    }

    defaultConfig {
        applicationId = "no.blakken.restaurants.maharaja"
        minSdk = 26
        targetSdk = 35
        versionCode = 1
        versionName = "1.0"
        buildConfigField("String", "API_BASE_URL", "\"$apiBaseUrl\"")
        buildConfigField("String", "RESTAURANT_APP_ID", "\"$restaurantAppId\"")
        buildConfigField("String", "WS_BASE_URL", "\"$websocketBaseUrl\"")
        buildConfigField("Boolean", "PLAY_INTEGRITY_REQUIRED", playIntegrityRequired.toString())
        buildConfigField("String", "APP_REGISTRATION_ID", "\"$appRegistrationId\"")
        buildConfigField(
            "String",
            "PLAY_INTEGRITY_CLOUD_PROJECT_NUMBER",
            "\"$playIntegrityCloudProjectNumber\"",
        )
    }

    buildFeatures {
        buildConfig = true
        compose = true
    }
}

dependencies {
    implementation(platform("androidx.compose:compose-bom:2024.12.01"))
    implementation("androidx.activity:activity-compose:1.10.0")
    implementation("androidx.compose.material3:material3")
    implementation("androidx.compose.ui:ui")
    implementation("androidx.compose.ui:ui-tooling-preview")
    implementation("androidx.lifecycle:lifecycle-runtime-ktx:2.8.7")
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-android:1.9.0")
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-play-services:1.9.0")
    implementation("com.google.android.play:integrity:1.6.0")
    implementation("com.squareup.okhttp3:okhttp:4.12.0")
    debugImplementation("androidx.compose.ui:ui-tooling")
}
