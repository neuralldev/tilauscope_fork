// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (c) 2026 Tilau
// This file is part of TilauScope.

import java.util.Properties

plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
    id("com.chaquo.python")
}

// The roast label's fonts are the desktop's (src/includes), copied in at build time rather than kept twice.
val labelFonts = layout.buildDirectory.dir("generated/labelFonts")
val copyLabelFonts by tasks.registering(Copy::class) {
    from("../../src/includes") { include("DejaVuSans.ttf", "DejaVuSans-Bold.ttf") }
    into(labelFonts.map { it.dir("fonts") })
}
// The machines' Artisan setups (.aset) the tablet reads, the desktop's, packaged at build time
// as the Python package machine_setups (tilauscope_mobile/machine.py).
val machineSetups = layout.buildDirectory.dir("generated/machineSetups")
val copyMachineSetups by tasks.registering(Copy::class) {
    from("../../src/includes/Machines") { include("Skywalker/skywalkerv2-ble.aset", "Skywalker/skywalkerv1-skycommand.aset") }
    into(machineSetups.map { it.dir("machine_setups") })
    doLast { machineSetups.get().file("machine_setups/__init__.py").asFile.writeText("") }
}
tasks.named("preBuild") { dependsOn(copyLabelFonts, copyMachineSetups) }
tasks.matching { it.name.endsWith("PythonSources") }.configureEach { dependsOn(copyMachineSetups) }

android {
    sourceSets { getByName("main") { assets.srcDir(labelFonts) } }
    namespace = "org.tilauscope.android.prototype"
    compileSdk = 35
    defaultConfig {
        applicationId = "org.tilauscope.android.prototype"
        minSdk = 26
        targetSdk = 35
        val version = Properties().apply { rootProject.file("version.properties").inputStream().use { load(it) } }
        versionCode = version.getProperty("versionCode").toInt()
        versionName = version.getProperty("versionName")
        ndk { abiFilters += listOf("arm64-v8a", "x86_64") }
    }
    // Release signing for the test APK: the key and its passwords stay outside the repository.
    val signingFile = file(System.getProperty("user.home") + "/.android/tilauscope-release.properties")
    if (signingFile.exists()) {
        val signing = Properties().apply { signingFile.inputStream().use { load(it) } }
        signingConfigs.create("release") {
            storeFile = file(signing.getProperty("storeFile"))
            storePassword = signing.getProperty("storePassword")
            keyAlias = signing.getProperty("keyAlias")
            keyPassword = signing.getProperty("keyPassword")
        }
        buildTypes.getByName("release") { signingConfig = signingConfigs.getByName("release") }
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions { jvmTarget = "17" }
    testOptions { unitTests.isIncludeAndroidResources = true } // the manifest and SDK Robolectric runs with
}

// Unit tests of the device protocols (app/src/test): no device. Robolectric gives the links and the
// session service an Android runtime on the JVM (test only, never in the APK).
dependencies {
    testImplementation("junit:junit:4.13.2")
    testImplementation("org.robolectric:robolectric:4.14.1")
}

chaquopy {
    defaultConfig { version = "3.14" }
    // The tablet core, plus the domain library shared with the desktop (src/tilaucore).
    // Nothing else of ../../src: the desktop's Qt and Artisan code never reaches the tablet.
    sourceSets {
        getByName("main") {
            srcDir("../python")
            srcDir("../../src")
            srcDir(machineSetups)
            include("tilauscope_mobile/**", "tilaucore/**", "machine_setups/**")
        }
    }
}
