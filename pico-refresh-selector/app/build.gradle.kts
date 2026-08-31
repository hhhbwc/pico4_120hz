plugins {
    id("com.android.application")
}

android {
    namespace = "com.picoxr.refreshselector"
    compileSdk = 35

    defaultConfig {
        applicationId = "com.picoxr.refreshselector"
        minSdk = 29
        targetSdk = 29
        versionCode = 1
        versionName = "1.0.0"
    }

    buildTypes {
        release {
            isMinifyEnabled = false
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_11
        targetCompatibility = JavaVersion.VERSION_11
    }
}

dependencies {
    compileOnly("de.robv.android.xposed:api:82")
}
