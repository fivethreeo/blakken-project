plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
    id("org.jetbrains.kotlin.plugin.compose")
}

android {
    namespace = "no.blakken.management"
    compileSdk = 35

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    kotlinOptions {
        jvmTarget = "17"
    }

    val apiBaseUrl = providers.gradleProperty("BLAKKEN_API_BASE_URL")
        .orElse("https://blakken.cavabonga.no/")
        .get()
    val websocketBaseUrl = providers.gradleProperty("BLAKKEN_WS_BASE_URL")
        .orElse("ws://10.0.2.2:8002/")
        .get()
    // Official Play distribution requires its linked Cloud project and app configuration UUID.
    val playIntegrityRequired = providers.gradleProperty("PLAY_INTEGRITY_REQUIRED")
        .orElse("true").get().toBooleanStrict()
    val playIntegrityCloudProjectNumber = providers.gradleProperty("PLAY_INTEGRITY_CLOUD_PROJECT_NUMBER")
        .orElse("0").get().toLong()
    val appRegistrationId = providers.gradleProperty("APP_REGISTRATION_ID").orElse("").get()
    require(appRegistrationId.isEmpty() || appRegistrationId.matches(
        Regex("[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"),
    )) { "APP_REGISTRATION_ID must be empty or a UUID." }

    defaultConfig {
        applicationId = "no.blakken.management"
        minSdk = 26
        targetSdk = 35
        versionCode = 1
        versionName = "1.0"
        buildConfigField("String", "API_BASE_URL", "\"$apiBaseUrl\"")
        buildConfigField("String", "WS_BASE_URL", "\"$websocketBaseUrl\"")
        buildConfigField("boolean", "PLAY_INTEGRITY_REQUIRED", playIntegrityRequired.toString())
        buildConfigField("long", "PLAY_INTEGRITY_CLOUD_PROJECT_NUMBER", "${playIntegrityCloudProjectNumber}L")
        buildConfigField("String", "APP_REGISTRATION_ID", "\"$appRegistrationId\"")
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
