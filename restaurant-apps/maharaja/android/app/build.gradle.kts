plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
    id("org.jetbrains.kotlin.plugin.compose")
}

val apiBaseUrl = providers.gradleProperty("BLAAKEN_API_BASE_URL")
    .orElse("http://10.0.2.2:8000/")
    .get()
val restaurantAppId = providers.gradleProperty("MAHARAJA_APP_ID")
    .orElse("REPLACE_WITH_RESTAURANT_APP_ID")
    .get()

android {
    namespace = "no.blakken.restaurants.maharaja"
    compileSdk = 35

    defaultConfig {
        applicationId = "no.blakken.restaurants.maharaja"
        minSdk = 26
        targetSdk = 35
        versionCode = 1
        versionName = "1.0"
        buildConfigField("String", "API_BASE_URL", "\"$apiBaseUrl\"")
        buildConfigField("String", "RESTAURANT_APP_ID", "\"$restaurantAppId\"")
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
    debugImplementation("androidx.compose.ui:ui-tooling")
}
